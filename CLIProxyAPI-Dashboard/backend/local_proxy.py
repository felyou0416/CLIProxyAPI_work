"""Detect the active local HTTP mixed-port (FlClash / MaoMaoCloud / Clash)."""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

DEFAULT_CANDIDATE_PORTS = (
    7890, 7891, 7892, 7893, 7897,
    10808, 10809,
    20171, 20172,
    10090, 6152, 6153, 2080, 8888,
)

_PROBE_URLS = (
    'http://www.gstatic.com/generate_204',
    'http://cp.cloudflare.com/generate_204',
)

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, object] = {'ts': 0.0, 'key': None, 'result': None}
_CACHE_TTL_SECONDS = 8.0


def _unique_ports(values) -> list[int]:
    out: list[int] = []
    for value in values or []:
        try:
            port = int(value)
        except Exception:
            continue
        if 1 <= port <= 65535 and port not in out:
            out.append(port)
    return out


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return ''


def _mixed_port_from_yaml(text: str) -> int:
    match = re.search(r'(?m)^mixed-port:\s*(\d+)\s*$', text or '')
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def _ports_from_system_proxy() -> list[int]:
    if os.name != 'nt':
        return []
    ports: list[int] = []
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Internet Settings',
        ) as key:
            try:
                winreg.QueryValueEx(key, 'ProxyEnable')
            except Exception:
                pass
            server, _ = winreg.QueryValueEx(key, 'ProxyServer')
        text = str(server or '').strip()
        if not text:
            return []
        for part in re.split(r'[;\s]+', text):
            part = part.strip()
            if not part:
                continue
            if '=' in part:
                part = part.split('=', 1)[1].strip()
            host_port = part
            if '://' in host_port:
                host_port = urlparse(host_port).netloc or host_port
            if ':' not in host_port:
                continue
            host, port_text = host_port.rsplit(':', 1)
            host = host.strip().strip('[]')
            if host not in {'127.0.0.1', 'localhost', '::1', ''}:
                continue
            try:
                ports.append(int(port_text))
            except Exception:
                continue
    except Exception:
        return []
    return _unique_ports(ports)


def _ports_from_app_configs() -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    home = Path.home()
    local = Path(os.environ.get('LOCALAPPDATA') or (home / 'AppData' / 'Local'))
    roaming = Path(os.environ.get('APPDATA') or (home / 'AppData' / 'Roaming'))

    candidates: list[tuple[Path, str]] = [
        (roaming / 'com.follow' / 'clash' / 'config.yaml', 'flclash-config'),
        (roaming / 'MaoMaoCloud' / 'MaoMaoCloud' / 'config.yaml', 'maomao-config'),
        (roaming / 'MaoMaoCloud' / 'config.yaml', 'maomao-config'),
        (roaming / 'io.github.clash-verge-rev.clash-verge-rev' / 'clash-verge.yaml', 'clash-verge'),
    ]
    for root, label in (
        (roaming / 'com.follow' / 'clash' / 'profiles', 'flclash-profile'),
        (roaming / 'MaoMaoCloud' / 'MaoMaoCloud' / 'profiles', 'maomao-profile'),
        (roaming / 'MaoMaoCloud' / 'profiles', 'maomao-profile'),
    ):
        if root.is_dir():
            for path in sorted(root.glob('*.yaml'))[:20]:
                candidates.append((path, label))

    for path, label in candidates:
        if not path.is_file():
            continue
        port = _mixed_port_from_yaml(_read_text(path))
        if port:
            found.append((port, f'{label}:{path.name}'))

    for prefs_path, label in (
        (roaming / 'com.follow' / 'clash' / 'shared_preferences.json', 'flclash-prefs'),
        (roaming / 'MaoMaoCloud' / 'MaoMaoCloud' / 'shared_preferences.json', 'maomao-prefs'),
        (roaming / 'MaoMaoCloud' / 'shared_preferences.json', 'maomao-prefs'),
        (local / 'com.follow' / 'clash' / 'shared_preferences.json', 'flclash-local-prefs'),
    ):
        if not prefs_path.is_file():
            continue
        try:
            payload = json.loads(_read_text(prefs_path) or '{}')
            flutter = payload.get('flutter.config')
            cfg = json.loads(flutter) if isinstance(flutter, str) else (flutter or {})
            patch = cfg.get('patchClashConfig') if isinstance(cfg, dict) else {}
            if isinstance(patch, dict):
                port = int(patch.get('mixed-port') or patch.get('mixed_port') or 0)
                if port > 0:
                    found.append((port, label))
        except Exception:
            continue

    return found


def _port_is_listening(port: int, host: str = '127.0.0.1', timeout: float = 0.12) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((host, int(port))) == 0
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _probe_http_proxy(port: int, timeout: float = 1.0) -> dict:
    proxy_url = f'http://127.0.0.1:{int(port)}'
    listening = _port_is_listening(port)
    result = {
        'port': int(port),
        'proxy_url': proxy_url,
        'listening': listening,
        'works': False,
        'proxy_like': False,
        'error': '',
    }
    if not listening:
        result['error'] = 'not_listening'
        return result

    # Clash mixed-port often answers HTTP 400 for GET /
    # Clash mixed-port usually answers HTTP 400/405 for GET /. That is enough
    # to know a local proxy is listening; skip slow generate_204 probes.
    try:
        opener = build_opener()
        req = Request(proxy_url + '/', method='GET')
        with opener.open(req, timeout=timeout) as resp:
            result['proxy_like'] = True
            result['works'] = True
            result['status'] = getattr(resp, 'status', None)
            return result
    except Exception as exc:
        msg = str(exc)
        if 'HTTP Error' in msg or '400' in msg or '405' in msg:
            result['proxy_like'] = True
            result['works'] = True
            result['error'] = ''
            return result
        result['error'] = msg[:160]

    try:
        opener = build_opener(ProxyHandler({'http': proxy_url, 'https': proxy_url}))
        for probe in _PROBE_URLS:
            try:
                req = Request(probe, method='GET')
                with opener.open(req, timeout=timeout) as resp:
                    status = int(getattr(resp, 'status', 0) or 0)
                    if status in (200, 204):
                        result['works'] = True
                        result['proxy_like'] = True
                        result['status'] = status
                        result['error'] = ''
                        return result
                    result['proxy_like'] = True
                    result['status'] = status
            except Exception as exc:
                result['error'] = str(exc)[:160]
                if 'HTTP Error' in result['error']:
                    result['proxy_like'] = True
    except Exception as exc:
        result['error'] = str(exc)[:160]

    if result['proxy_like']:
        result['works'] = True
    return result


def collect_candidate_ports(extra_ports: list[int] | None = None) -> list[dict]:
    scored: dict[int, dict] = {}

    def add(port: int, source: str, weight: int = 1):
        try:
            port = int(port)
        except Exception:
            return
        if port < 1 or port > 65535:
            return
        item = scored.setdefault(port, {'port': port, 'sources': [], 'weight': 0})
        if source and source not in item['sources']:
            item['sources'].append(source)
        item['weight'] += weight

    for port in DEFAULT_CANDIDATE_PORTS:
        add(port, 'default', 1)
    for port in extra_ports or []:
        add(port, 'extra', 5)
    for port in _ports_from_system_proxy():
        add(port, 'system-proxy', 4)
    for port, source in _ports_from_app_configs():
        add(port, source, 6)

    # Only probe listening for non-default candidates first (fast path).
    # Default ports are checked later only if needed during detect.
    for port, item in list(scored.items()):
        sources = item.get('sources') or []
        if sources == ['default']:
            item['listening'] = None
            continue
        if _port_is_listening(port):
            item['weight'] += 10
            item['listening'] = True
        else:
            item['listening'] = False

    return sorted(scored.values(), key=lambda item: (-int(item['weight']), int(item['port'])))


def detect_local_http_proxy(
    extra_ports: list[int] | None = None,
    prefer_port: int | None = None,
    use_cache: bool = True,
) -> dict:
    """Pick the best currently usable local mixed-port for CPA proxy-url."""
    cache_key = (
        tuple(sorted(int(p) for p in (extra_ports or []) if str(p).strip())),
        int(prefer_port) if prefer_port else 0,
    )
    now = time.monotonic()
    if use_cache:
        with _CACHE_LOCK:
            if (
                _CACHE.get('key') == cache_key
                and isinstance(_CACHE.get('result'), dict)
                and (now - float(_CACHE.get('ts') or 0.0)) < _CACHE_TTL_SECONDS
            ):
                return dict(_CACHE['result'])  # type: ignore[arg-type]

    candidates = collect_candidate_ports(extra_ports=extra_ports)
    probes: list[dict] = []

    ordered_ports: list[int] = []
    if prefer_port:
        try:
            ordered_ports.append(int(prefer_port))
        except Exception:
            pass
    for item in candidates:
        port = int(item['port'])
        if port not in ordered_ports:
            ordered_ports.append(port)

    best = None
    for port in ordered_ports:
        meta = next((item for item in candidates if int(item['port']) == int(port)), {})
        sources = list(meta.get('sources') or [])
        weight = int(meta.get('weight') or 0)
        # Skip closed ports quickly unless preferred.
        if not _port_is_listening(port) and not (prefer_port and int(port) == int(prefer_port)):
            probes.append({
                'port': int(port),
                'proxy_url': f'http://127.0.0.1:{int(port)}',
                'listening': False,
                'works': False,
                'proxy_like': False,
                'error': 'not_listening',
                'sources': sources,
                'weight': weight,
            })
            continue

        probe = _probe_http_proxy(port)
        probe['sources'] = sources
        probe['weight'] = weight
        probes.append(probe)
        if not probe.get('works'):
            continue
        # Candidates are ordered by weight desc, so the first working port is best.
        best = probe
        break

    if not best:
        result = {
            'ok': False,
            'proxy_url': '',
            'port': 0,
            'source': '',
            'candidates': probes[:12],
            'message': 'No local HTTP mixed-port proxy detected.',
        }
    else:
        source = ','.join(best.get('sources') or []) or 'detected'
        result = {
            'ok': True,
            'proxy_url': str(best.get('proxy_url') or ''),
            'port': int(best.get('port') or 0),
            'source': source,
            'works': True,
            'candidates': probes[:12],
            'message': f'Detected local proxy {best.get("proxy_url")} ({source}).',
        }

    if use_cache:
        with _CACHE_LOCK:
            _CACHE['ts'] = time.monotonic()
            _CACHE['key'] = cache_key
            _CACHE['result'] = dict(result)
    return result


def is_local_proxy_url(proxy_url: str | None) -> bool:
    raw = str(proxy_url or '').strip()
    if not raw or raw.lower() in {'direct', 'none'}:
        return False
    try:
        parsed = urlparse(raw if '://' in raw else f'http://{raw}')
    except Exception:
        return False
    host = (parsed.hostname or '').strip().lower()
    return host in {'127.0.0.1', 'localhost', '::1'}


def remap_local_proxy_url(proxy_url: str | None, detected_proxy_url: str | None) -> str:
    """Rewrite a local mixed-port proxy-url to the currently detected one."""
    raw = str(proxy_url or '').strip()
    detected = str(detected_proxy_url or '').strip()
    if not raw or raw.lower() in {'direct', 'none'}:
        return raw
    if not detected:
        return raw
    if not is_local_proxy_url(raw):
        return raw
    return detected
