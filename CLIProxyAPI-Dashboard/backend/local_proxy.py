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
    10090, 9790,  # MaoMaoCloud / mihomo common mixed + control ports
    10808, 10809,
    20171, 20172,
    6152, 6153, 2080, 8888,
)

# Control-panel ports sometimes listen but are not HTTP mixed-ports.
_CONTROL_PORT_HINTS = {9090, 9091, 9790, 47890}

_PROBE_URLS = (
    'http://www.gstatic.com/generate_204',
    'http://cp.cloudflare.com/generate_204',
)

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, object] = {'ts': 0.0, 'key': None, 'result': None}
_CACHE_TTL_SECONDS = 8.0

# Egress failure tracking — when a proxy fails for a target, skip it briefly.
_EGRESS_FAILURE_TTL = 15.0  # seconds to avoid a failed egress path
_EGRESS_FAILURES: dict[str, float] = {}  # key → monotonic timestamp of failure


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
        (Path(r'C:/Program Files (x86)/MAOMAOYUNAPP/resources/extra/config.yaml'), 'maomao-install-config'),
        (Path(r'C:/Program Files/MAOMAOYUNAPP/resources/extra/config.yaml'), 'maomao-install-config'),
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
        # Bundled MaoMao configs may be encrypted/binary; skip non-text.
        text = _read_text(path)
        if not text or '\x00' in text[:200] or not re.search(r'(?m)^(mixed-port|port|socks-port):', text):
            continue
        port = _mixed_port_from_yaml(text)
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


def _ports_from_running_proxy_processes() -> list[tuple[int, str]]:
    """Discover mixed-ports from currently listening FlClash / mihomo / MaoMao processes."""
    if os.name != 'nt':
        return []
    try:
        import subprocess

        ps = r'''
$names = 'FlClashCore','FlClash','mihomo-windows-386','mihomo','MaoMaoCloud','clash-meta','Clash for Windows'
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  try {
    $proc = Get-Process -Id $_.OwningProcess -ErrorAction Stop
    $n = [string]$proc.ProcessName
    $match = $false
    foreach ($name in $names) { if ($n -like ("*" + $name + "*") -or $n -match 'mihomo|FlClash|MaoMao|clash') { $match = $true; break } }
    if (-not $match) { return }
    $port = [int]$_.LocalPort
    if ($port -lt 1024) { return }
    '{0}|{1}' -f $port, $n
  } catch {}
}
'''
        completed = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=4,
        )
    except Exception:
        return []

    found: list[tuple[int, str]] = []
    for line in (completed.stdout or '').splitlines():
        line = line.strip()
        if '|' not in line:
            continue
        port_text, name = line.split('|', 1)
        try:
            port = int(port_text)
        except Exception:
            continue
        if port in _CONTROL_PORT_HINTS:
            # Still record, but mark as control so weight stays low later.
            found.append((port, f'proc-control:{name}'))
        else:
            found.append((port, f'proc:{name}'))
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

    # Live process listeners beat stale config / system-proxy leftovers.
    for port, source in _ports_from_running_proxy_processes():
        if str(source).startswith('proc-control:'):
            add(port, source, 2)
        else:
            add(port, source, 20)

    for port, source in _ports_from_app_configs():
        add(port, source, 6)

    # System proxy only counts when that port is actually listening.
    for port in _ports_from_system_proxy():
        if _port_is_listening(port):
            add(port, 'system-proxy', 8)
        else:
            add(port, 'system-proxy-stale', 0)

    for port, item in list(scored.items()):
        sources = item.get('sources') or []
        if sources == ['default']:
            item['listening'] = None
            continue
        if _port_is_listening(port):
            item['weight'] += 12
            item['listening'] = True
            # Prefer real mixed-ports over known control ports.
            if port in _CONTROL_PORT_HINTS:
                item['weight'] -= 15
        else:
            item['listening'] = False
            # Dead ports from old FlClash/system-proxy must not outrank a live MaoMao port.
            item['weight'] = min(int(item['weight']), 3)

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
    # Only honor prefer_port when it is currently listening; otherwise fall through
    # to the live FlClash/MaoMao port (this is what breaks after switching clients).
    if prefer_port:
        try:
            prefer_port_i = int(prefer_port)
            if _port_is_listening(prefer_port_i):
                ordered_ports.append(prefer_port_i)
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
        # Skip closed ports quickly.
        if not _port_is_listening(port):
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
        # Skip pure control ports if we already have no mixed-port success yet —
        # but only accept them as last resort (weight already demoted).
        if port in _CONTROL_PORT_HINTS and not probe.get('proxy_like'):
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


def list_listening_proxy_ports(extra_ports: list[int] | None = None) -> list[int]:
    """Homepage-aligned candidate ports that are currently listening."""
    ports: list[int] = []
    for item in collect_candidate_ports(extra_ports=extra_ports):
        try:
            port = int(item.get('port') or 0)
        except Exception:
            continue
        if port <= 0 or port in ports or port in _CONTROL_PORT_HINTS:
            continue
        if item.get('listening') is False:
            continue
        if _port_is_listening(port):
            ports.append(port)
    for port in DEFAULT_CANDIDATE_PORTS:
        if port in ports or port in _CONTROL_PORT_HINTS:
            continue
        if _port_is_listening(port):
            ports.append(port)
    return ports


def _normalize_egress_proxy_url(proxy_url: str | None) -> str:
    raw = str(proxy_url or '').strip()
    if not raw or raw.lower() in {'none', 'off', 'disabled'}:
        return 'direct'
    if raw.lower() == 'direct':
        return 'direct'
    if '://' not in raw:
        raw = f'http://{raw}'
    return raw


def _proxy_handler_for_egress(proxy_url: str | None) -> ProxyHandler:
    normalized = _normalize_egress_proxy_url(proxy_url)
    if normalized == 'direct':
        return ProxyHandler({})
    return ProxyHandler({'http': normalized, 'https': normalized})


def probe_target_via_proxy(
    target_url: str,
    proxy_url: str | None = None,
    timeout: float = 4.0,
    headers: dict | None = None,
) -> dict:
    """Probe a concrete upstream URL via direct or a local mixed-port proxy."""
    target = str(target_url or '').strip()
    normalized_proxy = _normalize_egress_proxy_url(proxy_url)
    result = {
        'ok': False,
        'proxy_url': normalized_proxy,
        'target_url': target,
        'status': 0,
        'latency_ms': None,
        'error': '',
    }
    if not target:
        result['error'] = 'missing_target'
        return result

    opener = build_opener(_proxy_handler_for_egress(normalized_proxy))
    req_headers = {'User-Agent': 'cliproxyapi-dashboard-egress-probe'}
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).strip() and value is not None:
                req_headers[str(key)] = str(value)
    request = Request(target, headers=req_headers, method='GET')
    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as resp:
            status = int(getattr(resp, 'status', 0) or 0)
            try:
                resp.read(512)
            except Exception:
                pass
            result['status'] = status
            result['latency_ms'] = int((time.monotonic() - started) * 1000)
            # Any HTTP response means the egress path itself works.
            result['ok'] = 100 <= status < 600
            if not result['ok']:
                result['error'] = f'http_{status}'
            return result
    except Exception as exc:
        result['latency_ms'] = int((time.monotonic() - started) * 1000)
        msg = str(exc)
        # urllib HTTPError still proves the TCP/TLS path is usable.
        code = getattr(exc, 'code', None)
        try:
            code = int(code) if code is not None else None
        except Exception:
            code = None
        if code is not None:
            result['status'] = code
            result['ok'] = 100 <= code < 600
            if not result['ok']:
                result['error'] = f'http_{code}'
            return result
        result['error'] = msg[:180]
        return result


def _egress_probe_url(target_url: str) -> str:
    raw = str(target_url or '').strip()
    if not raw:
        return ''
    parsed = urlparse(raw if '://' in raw else f'http://{raw}')
    if not parsed.scheme or not parsed.netloc:
        return raw
    path = (parsed.path or '').rstrip('/')
    # OpenAI-compatible providers expose /v1/models cheaply.
    if path.endswith('/v1'):
        path = f'{path}/models'
    elif path.endswith('/v1/models'):
        pass
    elif not path or path == '/':
        path = '/v1/models'
    return f'{parsed.scheme}://{parsed.netloc}{path}'


def report_egress_failure(target_url: str, proxy_url: str | None = None) -> None:
    """Mark an egress path as failed so it is briefly avoided on next probe."""
    key = f'{_egress_probe_url(target_url)}|{_normalize_egress_proxy_url(proxy_url)}'
    _EGRESS_FAILURES[key] = time.monotonic()


def _is_egress_failed(target_url: str, proxy_url: str) -> bool:
    key = f'{_egress_probe_url(target_url)}|{proxy_url}'
    failed_at = _EGRESS_FAILURES.get(key)
    if failed_at is None:
        return False
    if (time.monotonic() - failed_at) > _EGRESS_FAILURE_TTL:
        _EGRESS_FAILURES.pop(key, None)
        return False
    return True


def choose_best_egress(
    target_url: str,
    *,
    include_direct: bool = True,
    prefer_proxy_url: str | None = None,
    headers: dict | None = None,
    timeout: float = 2.5,
    extra_ports: list[int] | None = None,
) -> dict:
    """Pick the best current egress the same way the homepage compares ports.

    Candidates = listening local mixed-ports (+ optional direct). Preference only
    reorders ties; the winner is always a working path to target_url. Probes run
    in parallel so rebuilds stay cheap when several providers share a host.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    probe_url = _egress_probe_url(target_url)
    prefer = _normalize_egress_proxy_url(prefer_proxy_url)

    candidates: list[str] = []
    if prefer and prefer != 'direct' and prefer not in candidates:
        candidates.append(prefer)
    for port in list_listening_proxy_ports(extra_ports=extra_ports):
        url = f'http://127.0.0.1:{int(port)}'
        if url not in candidates:
            candidates.append(url)
    if include_direct and 'direct' not in candidates:
        if prefer == 'direct':
            candidates.insert(0, 'direct')
        else:
            candidates.append('direct')
    if prefer == 'direct' and 'direct' in candidates:
        candidates = ['direct'] + [item for item in candidates if item != 'direct']

    probes: list[dict] = []
    pending: list[str] = []
    for proxy_url in candidates:
        # Skip recently-failed egress paths (unless it's the only candidate).
        if proxy_url != 'direct' and _is_egress_failed(probe_url, proxy_url):
            if len(candidates) > 1:
                probes.append({
                    'ok': False,
                    'proxy_url': proxy_url,
                    'target_url': probe_url,
                    'status': 0,
                    'latency_ms': None,
                    'error': 'recently_failed',
                })
                continue
        if proxy_url != 'direct' and is_local_proxy_url(proxy_url):
            try:
                port = int(urlparse(proxy_url).port or 0)
            except Exception:
                port = 0
            if port and not _port_is_listening(port):
                probes.append({
                    'ok': False,
                    'proxy_url': proxy_url,
                    'target_url': probe_url,
                    'status': 0,
                    'latency_ms': None,
                    'error': 'not_listening',
                })
                continue
        pending.append(proxy_url)

    if pending:
        workers = min(6, len(pending))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    probe_target_via_proxy,
                    probe_url,
                    proxy_url=proxy_url,
                    timeout=timeout,
                    headers=headers,
                ): proxy_url
                for proxy_url in pending
            }
            for future in as_completed(futures):
                proxy_url = futures[future]
                try:
                    probe = future.result()
                except Exception as exc:
                    probe = {
                        'ok': False,
                        'proxy_url': proxy_url,
                        'target_url': probe_url,
                        'status': 0,
                        'latency_ms': None,
                        'error': str(exc)[:180],
                    }
                probes.append(probe)

    best = None
    for probe in probes:
        if not probe.get('ok'):
            continue
        if best is None:
            best = probe
            continue
        best_latency = best.get('latency_ms')
        probe_latency = probe.get('latency_ms')
        if best_latency is None or (probe_latency is not None and probe_latency < best_latency):
            best = probe
            continue
        # Prefer homepage/user preference only when latency is essentially tied.
        if (
            prefer
            and probe_latency is not None
            and best_latency is not None
            and abs(int(probe_latency) - int(best_latency)) <= 30
            and str(probe.get('proxy_url') or '') == prefer
        ):
            best = probe

    if not best:
        return {
            'ok': False,
            'proxy_url': prefer if prefer else 'direct',
            'target_url': probe_url,
            'probes': probes,
            'message': 'No working egress path to target.',
        }

    return {
        'ok': True,
        'proxy_url': str(best.get('proxy_url') or 'direct'),
        'target_url': probe_url,
        'status': best.get('status'),
        'latency_ms': best.get('latency_ms'),
        'probes': probes,
        'message': f'Chose egress {best.get("proxy_url")} for {probe_url}',
    }
