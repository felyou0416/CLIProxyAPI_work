"""Windows system proxy controls for the dashboard homepage."""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Any

from backend.local_proxy import _port_is_listening, _probe_http_proxy, collect_candidate_ports, detect_local_http_proxy

_PROXY_SYNC_LOCK = threading.RLock()

PROXY_ENV_VARS = (
    'HTTP_PROXY',
    'HTTPS_PROXY',
    'ALL_PROXY',
    'http_proxy',
    'https_proxy',
    'all_proxy',
)

_FALLBACK_PORTS = (7890, 7891, 7897, 10090, 1080, 8080)


def _winreg():
    if os.name != 'nt':
        raise RuntimeError('系统代理管理仅支持 Windows。')
    import winreg  # type: ignore
    return winreg


def get_system_proxy() -> tuple[bool, str]:
    try:
        winreg = _winreg()
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Internet Settings',
        ) as key:
            enable, _ = winreg.QueryValueEx(key, 'ProxyEnable')
            try:
                server, _ = winreg.QueryValueEx(key, 'ProxyServer')
            except FileNotFoundError:
                server = ''
            return bool(enable), str(server or '').strip()
    except Exception as exc:
        return False, f'读取失败: {exc}'


def set_system_proxy(enable: bool, server: str = '') -> None:
    winreg = _winreg()
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r'Software\Microsoft\Windows\CurrentVersion\Internet Settings',
        0,
        winreg.KEY_WRITE,
    ) as key:
        winreg.SetValueEx(key, 'ProxyEnable', 0, winreg.REG_DWORD, 1 if enable else 0)
        if server:
            winreg.SetValueEx(key, 'ProxyServer', 0, winreg.REG_SZ, str(server))


def get_env_vars() -> dict[str, str]:
    return {key: os.environ.get(key, '') for key in PROXY_ENV_VARS}


def set_env_vars(proxy_url: str) -> None:
    value = str(proxy_url or '').strip()
    for var in PROXY_ENV_VARS:
        try:
            subprocess.run(['setx', var, value], capture_output=True, text=True, timeout=8)
        except Exception:
            pass
        os.environ[var] = value


def clear_env_vars() -> None:
    for var in PROXY_ENV_VARS:
        try:
            subprocess.run(['setx', var, ''], capture_output=True, text=True, timeout=8)
        except Exception:
            pass
        os.environ.pop(var, None)


def _port_from_server(server: str) -> int | None:
    text = str(server or '').strip()
    if not text or ':' not in text:
        return None
    try:
        return int(text.rsplit(':', 1)[-1])
    except Exception:
        return None


def list_available_ports() -> list[int]:
    ports: list[int] = []
    for item in collect_candidate_ports():
        try:
            port = int(item.get('port') or 0)
        except Exception:
            continue
        if port <= 0 or port in ports:
            continue
        if item.get('listening') is False:
            continue
        if _port_is_listening(port):
            ports.append(port)
    for port in _FALLBACK_PORTS:
        if port not in ports and _port_is_listening(port):
            ports.append(port)
    return ports


def pick_best_port(available_ports: list[int] | None = None) -> int | None:
    ports = list(available_ports or [])
    if not ports:
        detected = detect_local_http_proxy(use_cache=False)
        if detected.get('ok') and detected.get('port'):
            return int(detected['port'])
        ports = list_available_ports()
    for port in ports:
        probe = _probe_http_proxy(port)
        if probe.get('works'):
            return int(port)
    return None


def get_system_proxy_status() -> dict[str, Any]:
    enabled, server = get_system_proxy()
    current_port = _port_from_server(server) if enabled else None
    available_ports = list_available_ports()
    item = {
        'proxy_enabled': bool(enabled),
        'proxy_server': server if enabled else '',
        'current_port': current_port,
        'env_vars': get_env_vars(),
        'available_ports': available_ports,
    }
    return {
        'ok': True,
        'item': item,
        **item,
    }


def _synchronize_dashboard_proxy(proxy_url: str) -> dict[str, Any]:
    """Apply a selected local mixed port to every Dashboard-managed local override."""
    with _PROXY_SYNC_LOCK:
        from backend import auth, model_pool

        settings = auth.synchronize_local_proxy_settings(proxy_url)
        if not settings.get('ok'):
            return {'ok': False, 'message': settings.get('error') or 'Failed to synchronize model proxy settings.'}
        pools = model_pool.remap_local_pool_proxy_urls(proxy_url)
        if not pools.get('ok'):
            return {'ok': False, 'message': pools.get('error') or 'Failed to synchronize model pool settings.'}
        runtime = auth.rebuild_runtime_config_from_state()
        if not runtime.get('rebuilt') and runtime.get('reason') != 'no_auth_files':
            return {
                'ok': False,
                'message': runtime.get('error') or 'Failed to rebuild CPA runtime configuration.',
                'settings_updated': settings.get('settings_updated', 0),
                'pool_nodes_updated': pools.get('changed_nodes', 0),
                'cache_entries_cleared': settings.get('cache_entries_cleared', 0),
                'runtime': runtime,
            }
        return {
            'ok': True,
            'settings_updated': settings.get('settings_updated', 0),
            'pool_nodes_updated': pools.get('changed_nodes', 0),
            'cache_entries_cleared': settings.get('cache_entries_cleared', 0),
            'runtime': runtime,
        }


def _configure_selected_port(port: int) -> dict[str, Any]:
    proxy_url = f'http://127.0.0.1:{port}'
    set_system_proxy(True, f'127.0.0.1:{port}')
    set_env_vars(proxy_url)
    sync = _synchronize_dashboard_proxy(proxy_url)
    if not sync.get('ok'):
        return {
            'ok': False,
            'message': sync.get('message') or '系统代理已设置，但 Dashboard 同步失败。',
            'proxy_enabled': True,
            'port': port,
            'proxy_url': proxy_url,
            'synchronization': sync,
        }
    return {
        'ok': True,
        'message': (
            f'已切换到 127.0.0.1:{port}，并同步 {sync["settings_updated"]} 项代理规则、'
            f'{sync["pool_nodes_updated"]} 个轮询池节点。'
        ),
        'proxy_enabled': True,
        'port': port,
        'proxy_url': proxy_url,
        'synchronization': sync,
        'runtime_rebuilt': bool(sync['runtime'].get('rebuilt')),
    }


def configure_system_proxy() -> dict[str, Any]:
    available_ports = list_available_ports()
    if not available_ports:
        return {
            'ok': False,
            'message': '未检测到任何可用的代理端口！请确保代理软件已启动。',
        }
    best_port = pick_best_port(available_ports)
    if not best_port:
        return {
            'ok': False,
            'message': '所有可用端口测试失败，无法自动配置代理。',
            'available_ports': available_ports,
        }
    return _configure_selected_port(best_port)


def toggle_system_proxy() -> dict[str, Any]:
    enabled, _server = get_system_proxy()
    if enabled:
        set_system_proxy(False)
        clear_env_vars()
        return {
            'ok': True,
            'message': '代理已停止，系统恢复正常状态。',
            'proxy_enabled': False,
            'port': None,
        }

    available_ports = list_available_ports()
    if not available_ports:
        return {
            'ok': False,
            'message': '未检测到可用端口，请先启动代理软件！',
        }
    best_port = pick_best_port(available_ports)
    if not best_port:
        return {
            'ok': False,
            'message': '没有可用的代理端口，无法启动代理。',
            'available_ports': available_ports,
        }
    return _configure_selected_port(best_port)


def restore_system_proxy_default() -> dict[str, Any]:
    set_system_proxy(False)
    clear_env_vars()
    return {
        'ok': True,
        'message': '已恢复默认状态，系统不再使用代理。',
        'proxy_enabled': False,
        'port': None,
    }


def set_system_proxy_port(port: int, require_listening: bool = True) -> dict[str, Any]:
    """Force system proxy + env vars to a specific local mixed-port."""
    try:
        port_i = int(port)
    except Exception:
        return {'ok': False, 'message': '端口无效。'}
    if port_i < 1 or port_i > 65535:
        return {'ok': False, 'message': f'端口无效: {port}'}

    listening = _port_is_listening(port_i)
    if require_listening and not listening:
        return {
            'ok': False,
            'message': f'端口 {port_i} 未在监听，请先启动对应代理软件。',
            'port': port_i,
            'listening': False,
        }

    result = _configure_selected_port(port_i)
    result['listening'] = listening
    try:
        result['works'] = bool(_probe_http_proxy(port_i).get('works')) if listening else False
    except Exception:
        result['works'] = False
    return result
