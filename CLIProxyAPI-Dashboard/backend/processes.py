import subprocess
import psutil
import threading
import time
import socket
import os
import signal
import re
import base64
import json
import ipaddress
from pathlib import Path
from backend.paths import (
    CLI_EXE,
    PROJECT_ROOT,
    BASE_CONFIG,
    DEVICE_LOGIN_STDOUT,
    DEVICE_LOGIN_STDERR,
    PROXY_STDOUT,
    PROXY_STDERR,
    RUNTIME_CONFIG,
    PROXY_ROOT,
    MEDIA_PROXY_ROOT,
    DASHBOARD_ROOT,
    STORAGE_DIR,
    LOGS_DIR,
    MEDIA_PROXY_STDOUT,
    MEDIA_PROXY_STDERR,
    RUNTIME_VARIANT,
    POOL_AUTH_DIR,
)
from backend.auth import build_runtime_config, list_auth_files, build_auth_ref, canonicalize_auth_ref
from backend.state import load_state, save_state, get_proxy_bind_host, get_proxy_api_key, normalize_route_strategy
from backend.runtime_env import command_exists, is_windows, cli_binary_hint

process_lock = threading.Lock()

def get_process_name(pid):
    """Return the process name for a given PID using psutil, or None if unavailable."""
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None
processes = {'device_login': None, 'proxy': None, 'media_proxy': None, 'oauth_manager': None, 'openclaw': None}
tool_processes: dict = {}
tool_states: dict = {}
DEFAULT_TRUSTED_REMOTE_ADDRESSES = ['fd7a:115c:a1e0::9e39:c580', '100.89.197.128']
OAUTH_MANAGER_DIR = Path(r'E:\U_App\oauth-manager')
OAUTH_MANAGER_STDOUT = OAUTH_MANAGER_DIR / 'dashboard.stdout.log'
OAUTH_MANAGER_STDERR = OAUTH_MANAGER_DIR / 'dashboard.stderr.log'
OPENCLAW_HOME = Path.home() / '.openclaw'
OPENCLAW_GATEWAY_CMD = OPENCLAW_HOME / 'gateway.cmd'
OPENCLAW_CMD = Path.home() / 'AppData' / 'Roaming' / 'npm' / 'openclaw.cmd'
OPENCLAW_STDOUT = LOGS_DIR / 'openclaw.stdout.log'
OPENCLAW_STDERR = LOGS_DIR / 'openclaw.stderr.log'
FIREWALL_RULES = [
    {
        'id': 'dashboard',
        'display_name': 'CLIProxyAPI Dashboard TCP 8765',
        'port': 8765,
        'description': 'Allow LAN access to CLIProxyAPI Dashboard panel',
    },
    {
        'id': 'proxy',
        'display_name': 'CLIProxyAPI Proxy TCP 8317',
        'port': 8317,
        'description': 'Allow LAN access to CLIProxyAPI proxy API',
    },
]


def _creationflags():
    return getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) if is_windows() else 0


def _cli_binary_ready():
    path = Path(CLI_EXE)
    return path.exists() and path.is_file()


def _cli_unavailable_message():
    return f'RelayX CLI binary was not found at {CLI_EXE}. {cli_binary_hint()}'


def _managed_proxy_process_names():
    return {'cli-proxy-api.exe', 'cliproxyapi.exe', 'cli-proxy-api', 'cliproxyapi'}


def media_proxy_port():
    return 8320


def _tool_log_path(tool_logs_dir, tool_id: str, suffix='stdout'):
    return tool_logs_dir / f'{tool_id}.{suffix}.log'


def _set_tool_state(tool_id: str, *, running: bool, returncode=None, error: str | None = None, pid: int | None = None):
    with process_lock:
        state = tool_states.setdefault(tool_id, {})
        state.update({'running': running, 'returncode': returncode, 'error': error, 'pid': pid if pid is not None else state.get('pid'), 'updated_at': time.time()})
        if not running and tool_id in tool_processes:
            tool_processes.pop(tool_id, None)


def process_alive(proc):
    return proc is not None and proc.poll() is None


def kill_process(proc):
    if not process_alive(proc):
        return False
    try:
        proc.terminate()
        proc.wait(timeout=5)
        return True
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=5)
            return True
        except Exception:
            return False


def find_proxy_listener_pid(port: int = 8317):
    if is_windows():
        try:
            output = subprocess.check_output(['netstat', '-ano', '-p', 'tcp'], text=True, stderr=subprocess.DEVNULL)
            for line in output.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0].upper() == 'TCP':
                    local = parts[1]
                    state = parts[3]
                    pid_str = parts[4]
                    if state.upper() == 'LISTENING' and (local.endswith(f':{port}') or local.endswith(f']:{port}')):
                        return int(pid_str)
        except Exception:
            pass
        return None
    if command_exists('lsof'):
        try:
            output = subprocess.check_output(['lsof', '-ti', f'tcp:{port}', '-sTCP:LISTEN'], text=True, stderr=subprocess.DEVNULL).strip()
            return int(output.splitlines()[0]) if output else None
        except Exception:
            return None
    if command_exists('ss'):
        try:
            output = subprocess.check_output(['ss', '-ltnp'], text=True, stderr=subprocess.DEVNULL)
        except Exception:
            return None
        suffix = f':{port}'
        for line in output.splitlines():
            if suffix not in line:
                continue
            if 'pid=' not in line:
                continue
            fragment = line.split('pid=', 1)[1]
            pid_text = fragment.split(',', 1)[0].strip()
            if pid_text:
                try:
                    return int(pid_text)
                except ValueError:
                    return None
    return None


def get_dashboard_port():
    value = (os.environ.get('CLIPROXYAPI_DASHBOARD_PORT', '8765') or '8765').strip() or '8765'
    try:
        return int(value)
    except ValueError:
        return 8765


def get_dashboard_bind_host():
    return (os.environ.get('CLIPROXYAPI_DASHBOARD_HOST', '127.0.0.1') or '127.0.0.1').strip() or '127.0.0.1'


def stop_dashboard_panel(delay_seconds: float = 0.5):
    def _stop_later():
        time.sleep(delay_seconds)
        os._exit(0)

    threading.Thread(target=_stop_later, name='dashboard-stop', daemon=True).start()
    return {'ok': True, 'message': 'Dashboard panel is stopping.'}


def restart_dashboard_panel(delay_seconds: float = 0.5):
    def _restart_later():
        time.sleep(delay_seconds)
        ps_script = DASHBOARD_ROOT / 'start_dashboard.ps1'
        if ps_script.exists():
            subprocess.Popen(
                ['powershell', '-ExecutionPolicy', 'Bypass', '-File', str(ps_script)],
                cwd=str(DASHBOARD_ROOT),
                creationflags=subprocess.CREATE_NEW_CONSOLE if is_windows() else 0
            )
        else:
            bat_script = DASHBOARD_ROOT / 'start_dashboard.bat'
            if bat_script.exists():
                subprocess.Popen(
                    [str(bat_script)],
                    cwd=str(DASHBOARD_ROOT),
                    creationflags=subprocess.CREATE_NEW_CONSOLE if is_windows() else 0
                )
        os._exit(0)

    threading.Thread(target=_restart_later, name='dashboard-restart', daemon=True).start()
    return {'ok': True, 'message': 'Dashboard panel is restarting.'}



def _is_local_bind_address(address: str):
    value = str(address or '').strip().lower()
    return value in ('localhost', '::1') or value.startswith('127.')


def _is_wildcard_bind_address(address: str):
    value = str(address or '').strip().lower()
    return value in ('', '0.0.0.0', '::', '[::]')


_listener_addresses_cache = {}

def find_listener_local_addresses(port: int):
    now = time.time()
    cache_entry = _listener_addresses_cache.get(port)
    if cache_entry and now - cache_entry['time'] < 3.0:
        return cache_entry['value']
    
    val = _find_listener_local_addresses_uncached(port)
    _listener_addresses_cache[port] = {'value': val, 'time': now}
    return val

def _find_listener_local_addresses_uncached(port: int):
    if is_windows():
        try:
            output = subprocess.check_output(['netstat', '-ano', '-p', 'tcp'], text=True, stderr=subprocess.DEVNULL)
            addresses = []
            for line in output.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0].upper() == 'TCP':
                    local = parts[1]
                    state = parts[3]
                    if state.upper() == 'LISTENING' and (local.endswith(f':{port}') or local.endswith(f']:{port}')):
                        if local.startswith('['):
                            ip = local.split(']:')[0].strip('[')
                        else:
                            ip = local.rsplit(':', 1)[0]
                        if ip not in addresses:
                            addresses.append(ip)
            return addresses
        except Exception:
            return []
    if command_exists('ss'):
        try:
            output = subprocess.check_output(['ss', '-ltn'], text=True, stderr=subprocess.DEVNULL)
        except Exception:
            return []
        suffix = f':{port}'
        addresses = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 4 or suffix not in parts[3]:
                continue
            address = parts[3].rsplit(':', 1)[0].strip('[]')
            if address:
                addresses.append(address)
        return addresses
    return []


def dashboard_allows_remote_access(port: int | None = None):
    port = port or get_dashboard_port()
    listener_addresses = find_listener_local_addresses(port)
    if listener_addresses:
        return any(
            _is_wildcard_bind_address(address) or not _is_local_bind_address(address)
            for address in listener_addresses
        )
    bind_host = get_dashboard_bind_host()
    return _is_wildcard_bind_address(bind_host) or not _is_local_bind_address(bind_host)


def _firewall_rule_status(rule):
    expected_protocol = str(rule.get('protocol') or 'TCP').upper()
    item = {
        'id': rule['id'],
        'display_name': rule['display_name'],
        'port': rule['port'],
        'exists': False,
        'enabled': False,
        'action': None,
        'direction': None,
        'profile': None,
        'protocol': expected_protocol,
        'local_port': str(rule['port']),
        'remote_address': None,
        'ok': False,
    }
    if not is_windows() or not command_exists('powershell'):
        item['message'] = 'Windows firewall management is only available on Windows with PowerShell.'
        return item
    script = f"""
$rule = Get-NetFirewallRule -DisplayName '{rule['display_name']}' -ErrorAction SilentlyContinue
if ($null -eq $rule) {{
  [pscustomobject]@{{ exists=$false }}
}} else {{
  $port = $rule | Get-NetFirewallPortFilter
  $address = $rule | Get-NetFirewallAddressFilter
  [pscustomobject]@{{
    exists=$true
    enabled=[string]$rule.Enabled
    action=[string]$rule.Action
    direction=[string]$rule.Direction
    profile=[string]$rule.Profile
    protocol=[string]$port.Protocol
    local_port=[string]$port.LocalPort
    remote_address=[string]$address.RemoteAddress
  }}
}}
"""
    try:
        command = f"& {{ {script} }} | ConvertTo-Json -Compress"
        output = subprocess.check_output(
            ['powershell', '-NoProfile', '-Command', command],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=6,
            creationflags=_creationflags(),
        ).strip()
        parsed = json.loads(output) if output else {}
    except Exception as exc:
        item['message'] = f'Failed to inspect firewall rule: {exc}'
        return item
    item['exists'] = bool(parsed.get('exists'))
    if item['exists']:
        item['enabled'] = str(parsed.get('enabled') or '').lower() == 'true'
        item['action'] = parsed.get('action')
        item['direction'] = parsed.get('direction')
        item['profile'] = parsed.get('profile')
        item['protocol'] = parsed.get('protocol') or 'TCP'
        item['local_port'] = parsed.get('local_port') or str(rule['port'])
        item['remote_address'] = parsed.get('remote_address')
        item['ok'] = (
            item['enabled']
            and str(item['action']).lower() == 'allow'
            and str(item['direction']).lower() == 'inbound'
            and str(item['protocol']).lower() == expected_protocol.lower()
            and str(item['local_port']) == str(rule['port'])
            and str(item.get('remote_address') or '').lower() not in ('', 'any')
        )
    return item


def firewall_access_status():
    rules = [_firewall_rule_status(rule) for rule in FIREWALL_RULES]
    return {
        'supported': bool(is_windows() and command_exists('powershell')),
        'rules': rules,
        'all_ok': bool(rules and all(rule.get('ok') for rule in rules)),
    }


def normalize_firewall_ports(value):
    raw_items = value if isinstance(value, list) else [value]
    ports = []
    for item in raw_items:
        if isinstance(item, str):
            candidates = re.split(r'[\s,;]+', item.strip())
        else:
            candidates = [item]
        for candidate in candidates:
            if candidate in (None, ''):
                continue
            try:
                port = int(candidate)
            except (TypeError, ValueError):
                raise ValueError(f'Invalid port: {candidate}')
            if port < 1 or port > 65535:
                raise ValueError(f'Port out of range: {port}')
            if port not in ports:
                ports.append(port)
    if len(ports) > 20:
        raise ValueError('At most 20 ports can be managed at once.')
    return ports


def normalize_firewall_protocols(value):
    raw_items = value if isinstance(value, list) else [value]
    protocols = []
    for item in raw_items:
        for candidate in re.split(r'[\s,;]+', str(item or '').strip()):
            if not candidate:
                continue
            protocol = candidate.upper()
            if protocol == 'BOTH':
                for expanded in ('TCP', 'UDP'):
                    if expanded not in protocols:
                        protocols.append(expanded)
                continue
            if protocol not in ('TCP', 'UDP'):
                raise ValueError(f'Invalid protocol: {candidate}')
            if protocol not in protocols:
                protocols.append(protocol)
    return protocols or ['TCP']


def normalize_remote_addresses(value):
    if value in (None, '', []):
        value = DEFAULT_TRUSTED_REMOTE_ADDRESSES
    raw_items = value if isinstance(value, list) else [value]
    addresses = []
    for item in raw_items:
        for candidate in re.split(r'[\s,;]+', str(item or '').strip()):
            if not candidate:
                continue
            token = candidate.strip()
            lowered = token.lower()
            if lowered == 'any':
                raise ValueError('Remote address "Any" is not allowed. Use specific IPs or CIDR ranges.')
            if lowered in ('localsubnet', 'local_subnet'):
                normalized = 'LocalSubnet'
            else:
                try:
                    normalized = str(ipaddress.ip_network(token, strict=False))
                except ValueError:
                    try:
                        normalized = str(ipaddress.ip_address(token))
                    except ValueError:
                        raise ValueError(f'Invalid remote address: {candidate}')
            if normalized not in addresses:
                addresses.append(normalized)
    if not addresses:
        raise ValueError('At least one allowed source IP or CIDR is required.')
    if len(addresses) > 20:
        raise ValueError('At most 20 allowed source addresses can be managed at once.')
    return addresses


def normalize_external_remote_addresses(value):
    if value in (None, '', []):
        raise ValueError('At least one external source IP or CIDR is required.')
    addresses = normalize_remote_addresses(value)
    if any(str(addr).lower() == 'localsubnet' for addr in addresses):
        raise ValueError('LocalSubnet is not allowed here. Use specific external IPs or CIDR ranges.')
    return addresses


def _custom_firewall_rule(port: int, protocol: str = 'TCP'):
    protocol = str(protocol or 'TCP').upper()
    return {
        'id': f'custom-{protocol.lower()}-{port}',
        'display_name': f'CLIProxyAPI Custom {protocol} {port}',
        'port': int(port),
        'protocol': protocol,
        'description': f'Allow custom LAN access to {protocol} port {port}',
    }


def custom_firewall_status(ports, protocols=None):
    normalized = normalize_firewall_ports(ports) if ports else []
    normalized_protocols = normalize_firewall_protocols(protocols or ['TCP'])
    rules = [
        _firewall_rule_status(_custom_firewall_rule(port, protocol))
        for port in normalized
        for protocol in normalized_protocols
    ]
    return {
        'supported': bool(is_windows() and command_exists('powershell')),
        'ports': normalized,
        'protocols': normalized_protocols,
        'rules': rules,
        'all_ok': bool(rules and all(rule.get('ok') for rule in rules)),
    }


def _custom_firewall_apply_script(ports, protocols=None, remote_addresses=None):
    normalized = normalize_firewall_ports(ports)
    normalized_protocols = normalize_firewall_protocols(protocols or ['TCP'])
    normalized_remote = normalize_remote_addresses(remote_addresses)
    rows = '\n'.join(
        f"  @{{ Name='CLIProxyAPI Custom {protocol} {port}'; Protocol='{protocol}'; Port='{port}'; Desc='Allow custom LAN access to {protocol} port {port}' }}"
        for port in normalized
        for protocol in normalized_protocols
    )
    remote_rows = ', '.join(f"'{addr}'" for addr in normalized_remote)
    return f"""
$ErrorActionPreference = 'Stop'
$remoteAddresses = @({remote_rows})
$rules = @(
{rows}
)
foreach ($rule in $rules) {{
  $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
  if ($existing) {{
    Set-NetFirewallRule -DisplayName $rule.Name -Enabled True -Direction Inbound -Action Allow -Profile Any
    Set-NetFirewallPortFilter -AssociatedNetFirewallRule $existing -Protocol $rule.Protocol -LocalPort $rule.Port
    Set-NetFirewallAddressFilter -AssociatedNetFirewallRule $existing -RemoteAddress $remoteAddresses
  }} else {{
    New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Action Allow -Protocol $rule.Protocol -LocalPort $rule.Port -RemoteAddress $remoteAddresses -Profile Any -Description $rule.Desc | Out-Null
  }}
}}
"""


def _custom_firewall_remove_script(ports, protocols=None):
    normalized = normalize_firewall_ports(ports)
    normalized_protocols = normalize_firewall_protocols(protocols or ['TCP'])
    rows = '\n'.join(
        f"  'CLIProxyAPI Custom {protocol} {port}'"
        for port in normalized
        for protocol in normalized_protocols
    )
    return f"""
$ErrorActionPreference = 'Stop'
$rules = @(
{rows}
)
foreach ($name in $rules) {{
  Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}}
"""


def ensure_custom_firewall_ports(ports, protocols=None, remote_addresses=None, elevated: bool = True):
    normalized = normalize_firewall_ports(ports)
    normalized_protocols = normalize_firewall_protocols(protocols or ['TCP'])
    if not normalized:
        return {'ok': False, 'message': 'No ports were provided.', 'firewall': custom_firewall_status([], normalized_protocols)}
    normalized_remote = normalize_remote_addresses(remote_addresses)
    if not is_windows() or not command_exists('powershell'):
        return {
            'ok': False,
            'message': 'Firewall port allow is only supported on Windows with PowerShell.',
            'firewall': custom_firewall_status(normalized, normalized_protocols),
        }
    current = custom_firewall_status(normalized, normalized_protocols)
    if current.get('all_ok'):
        return {'ok': True, 'message': 'Firewall rules are already enabled.', 'firewall': current}
    script = _custom_firewall_apply_script(normalized, normalized_protocols, normalized_remote)
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            check=True,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=12,
            creationflags=_creationflags(),
        )
        return {'ok': True, 'message': 'Firewall rules are enabled.', 'firewall': custom_firewall_status(normalized, normalized_protocols)}
    except subprocess.CalledProcessError as exc:
        stderr = str(exc.stderr or '').strip()
        if not elevated:
            return {'ok': False, 'message': stderr or 'Failed to update firewall rules.', 'firewall': current}
    except Exception as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc), 'firewall': current}

    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        subprocess.Popen(
            ['powershell', '-NoProfile', '-Command', f"Start-Process -Verb RunAs -FilePath powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}')"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
        return {
            'ok': True,
            'pending_elevation': True,
            'message': 'Administrator approval was requested. Confirm the UAC prompt, then refresh this panel.',
            'firewall': current,
        }
    except Exception as exc:
        return {
            'ok': False,
            'message': f'Failed to request administrator approval: {exc}',
            'firewall': current,
        }


def remove_custom_firewall_ports(ports, protocols=None, elevated: bool = True):
    normalized = normalize_firewall_ports(ports)
    normalized_protocols = normalize_firewall_protocols(protocols or ['TCP'])
    if not normalized:
        return {'ok': False, 'message': 'No ports were provided.', 'firewall': custom_firewall_status([], normalized_protocols)}
    if not is_windows() or not command_exists('powershell'):
        return {
            'ok': False,
            'message': 'Firewall port remove is only supported on Windows with PowerShell.',
            'firewall': custom_firewall_status(normalized, normalized_protocols),
        }
    current = custom_firewall_status(normalized, normalized_protocols)
    script = _custom_firewall_remove_script(normalized, normalized_protocols)
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            check=True,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=12,
            creationflags=_creationflags(),
        )
        return {'ok': True, 'message': 'Firewall rules are removed.', 'firewall': custom_firewall_status(normalized, normalized_protocols)}
    except subprocess.CalledProcessError as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc.stderr or '').strip() or 'Failed to remove firewall rules.', 'firewall': current}
    except Exception as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc), 'firewall': current}

    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        subprocess.Popen(
            ['powershell', '-NoProfile', '-Command', f"Start-Process -Verb RunAs -FilePath powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}')"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
        return {
            'ok': True,
            'pending_elevation': True,
            'message': 'Administrator approval was requested. Confirm the UAC prompt, then refresh this panel.',
            'firewall': current,
        }
    except Exception as exc:
        return {
            'ok': False,
            'message': f'Failed to request administrator approval: {exc}',
            'firewall': current,
        }


def _external_firewall_rule(port: int, protocol: str = 'TCP'):
    protocol = str(protocol or 'TCP').upper()
    return {
        'id': f'external-{protocol.lower()}-{port}',
        'display_name': f'CLIProxyAPI External {protocol} {port}',
        'port': int(port),
        'protocol': protocol,
        'description': f'Allow selected external IPs to access {protocol} port {port}',
    }


def external_firewall_status(ports, protocols=None):
    normalized = normalize_firewall_ports(ports) if ports else []
    normalized_protocols = normalize_firewall_protocols(protocols or ['TCP'])
    rules = [
        _firewall_rule_status(_external_firewall_rule(port, protocol))
        for port in normalized
        for protocol in normalized_protocols
    ]
    return {
        'supported': bool(is_windows() and command_exists('powershell')),
        'ports': normalized,
        'protocols': normalized_protocols,
        'rules': rules,
        'all_ok': bool(rules and all(rule.get('ok') for rule in rules)),
    }


def _external_firewall_apply_script(ports, protocols=None, remote_addresses=None):
    normalized = normalize_firewall_ports(ports)
    normalized_protocols = normalize_firewall_protocols(protocols or ['TCP'])
    normalized_remote = normalize_external_remote_addresses(remote_addresses)
    rows = '\n'.join(
        f"  @{{ Name='CLIProxyAPI External {protocol} {port}'; Protocol='{protocol}'; Port='{port}'; Desc='Allow selected external IPs to access {protocol} port {port}' }}"
        for port in normalized
        for protocol in normalized_protocols
    )
    remote_rows = ', '.join(f"'{addr}'" for addr in normalized_remote)
    return f"""
$ErrorActionPreference = 'Stop'
$remoteAddresses = @({remote_rows})
$rules = @(
{rows}
)
foreach ($rule in $rules) {{
  $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
  if ($existing) {{
    Set-NetFirewallRule -DisplayName $rule.Name -Enabled True -Direction Inbound -Action Allow -Profile Any
    Set-NetFirewallPortFilter -AssociatedNetFirewallRule $existing -Protocol $rule.Protocol -LocalPort $rule.Port
    Set-NetFirewallAddressFilter -AssociatedNetFirewallRule $existing -RemoteAddress $remoteAddresses
  }} else {{
    New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Action Allow -Protocol $rule.Protocol -LocalPort $rule.Port -RemoteAddress $remoteAddresses -Profile Any -Description $rule.Desc | Out-Null
  }}
}}
"""


def _external_firewall_remove_script(ports, protocols=None):
    normalized = normalize_firewall_ports(ports)
    normalized_protocols = normalize_firewall_protocols(protocols or ['TCP'])
    rows = '\n'.join(
        f"  'CLIProxyAPI External {protocol} {port}'"
        for port in normalized
        for protocol in normalized_protocols
    )
    return f"""
$ErrorActionPreference = 'Stop'
$rules = @(
{rows}
)
foreach ($name in $rules) {{
  Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}}
"""


def ensure_external_firewall_ports(ports, protocols=None, remote_addresses=None, elevated: bool = True):
    normalized = normalize_firewall_ports(ports)
    normalized_protocols = normalize_firewall_protocols(protocols or ['TCP'])
    if not normalized:
        return {'ok': False, 'message': 'No ports were provided.', 'firewall': external_firewall_status([], normalized_protocols)}
    normalize_external_remote_addresses(remote_addresses)
    if not is_windows() or not command_exists('powershell'):
        return {
            'ok': False,
            'message': 'External firewall access is only supported on Windows with PowerShell.',
            'firewall': external_firewall_status(normalized, normalized_protocols),
        }
    current = external_firewall_status(normalized, normalized_protocols)
    script = _external_firewall_apply_script(normalized, normalized_protocols, remote_addresses)
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            check=True,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=12,
            creationflags=_creationflags(),
        )
        return {'ok': True, 'message': 'External firewall rules are enabled.', 'firewall': external_firewall_status(normalized, normalized_protocols)}
    except subprocess.CalledProcessError as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc.stderr or '').strip() or 'Failed to update external firewall rules.', 'firewall': current}
    except Exception as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc), 'firewall': current}
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        subprocess.Popen(
            ['powershell', '-NoProfile', '-Command', f"Start-Process -Verb RunAs -FilePath powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}')"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
        return {
            'ok': True,
            'pending_elevation': True,
            'message': 'Administrator approval was requested. Confirm the UAC prompt, then refresh this panel.',
            'firewall': current,
        }
    except Exception as exc:
        return {'ok': False, 'message': f'Failed to request administrator approval: {exc}', 'firewall': current}


def remove_external_firewall_ports(ports, protocols=None, elevated: bool = True):
    normalized = normalize_firewall_ports(ports)
    normalized_protocols = normalize_firewall_protocols(protocols or ['TCP'])
    if not normalized:
        return {'ok': False, 'message': 'No ports were provided.', 'firewall': external_firewall_status([], normalized_protocols)}
    if not is_windows() or not command_exists('powershell'):
        return {
            'ok': False,
            'message': 'External firewall remove is only supported on Windows with PowerShell.',
            'firewall': external_firewall_status(normalized, normalized_protocols),
        }
    current = external_firewall_status(normalized, normalized_protocols)
    script = _external_firewall_remove_script(normalized, normalized_protocols)
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            check=True,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=12,
            creationflags=_creationflags(),
        )
        return {'ok': True, 'message': 'External firewall rules are removed.', 'firewall': external_firewall_status(normalized, normalized_protocols)}
    except subprocess.CalledProcessError as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc.stderr or '').strip() or 'Failed to remove external firewall rules.', 'firewall': current}
    except Exception as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc), 'firewall': current}
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        subprocess.Popen(
            ['powershell', '-NoProfile', '-Command', f"Start-Process -Verb RunAs -FilePath powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}')"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
        return {
            'ok': True,
            'pending_elevation': True,
            'message': 'Administrator approval was requested. Confirm the UAC prompt, then refresh this panel.',
            'firewall': current,
        }
    except Exception as exc:
        return {'ok': False, 'message': f'Failed to request administrator approval: {exc}', 'firewall': current}


def _portproxy_rows():
    if not is_windows() or not command_exists('netsh'):
        return []
    try:
        output = subprocess.check_output(
            ['netsh', 'interface', 'portproxy', 'show', 'v4tov4'],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=6,
            creationflags=_creationflags(),
        )
    except Exception:
        return []
    rows = []
    for line in output.splitlines():
        match = re.match(r'^\s*(\d{1,3}(?:\.\d{1,3}){3}|\*)\s+(\d+)\s+(\d{1,3}(?:\.\d{1,3}){3})\s+(\d+)\s*$', line)
        if not match:
            continue
        rows.append({
            'listen_address': match.group(1),
            'listen_port': int(match.group(2)),
            'connect_address': match.group(3),
            'connect_port': int(match.group(4)),
        })
    return rows


def _tcp_listener_rows(ports):
    normalized = normalize_firewall_ports(ports) if ports else []
    if not normalized:
        return []
    try:
        output = subprocess.check_output(
            ['cmd', '/c', 'netstat -ano -p tcp | findstr LISTENING'],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=_creationflags(),
        )
    except subprocess.CalledProcessError as exc:
        output = exc.output or ''
    except Exception:
        return []
    ports_set = set(normalized)
    rows = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != 'TCP' or parts[3].upper() != 'LISTENING':
            continue
        local = parts[1]
        if local.startswith('['):
            match = re.match(r'^\[(.*)\]:(\d+)$', local)
        else:
            match = re.match(r'^(.*):(\d+)$', local)
        if not match:
            continue
        port = int(match.group(2))
        if port not in ports_set:
            continue
        pid = int(parts[4])
        rows.append({
            'local_address': match.group(1),
            'local_port': port,
            'owning_process': pid,
            'process_name': '',
        })
    return rows


def _udp_endpoint_rows(ports):
    normalized = normalize_firewall_ports(ports) if ports else []
    if not normalized:
        return []
    try:
        output = subprocess.check_output(
            ['netstat', '-ano', '-p', 'udp'],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=_creationflags(),
        )
    except subprocess.CalledProcessError as exc:
        output = exc.output or ''
    except Exception:
        return []
    ports_set = set(normalized)
    rows = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0].upper() != 'UDP':
            continue
        local = parts[1]
        if local.startswith('['):
            match = re.match(r'^\[(.*)\]:(\d+)$', local)
        else:
            match = re.match(r'^(.*):(\d+)$', local)
        if not match:
            continue
        port = int(match.group(2))
        if port not in ports_set:
            continue
        rows.append({
            'local_address': match.group(1),
            'local_port': port,
            'owning_process': int(parts[-1]) if str(parts[-1]).isdigit() else None,
            'process_name': '',
        })
    return rows


def _has_portproxy_backend_listener(listeners, port):
    return any(
        int(row.get('local_port') or 0) == int(port)
        and str(row.get('local_address') or '') == '127.0.0.1'
        for row in listeners
    )


def port_binding_status():
    portproxy = [
        row for row in _portproxy_rows()
        if str(row.get('listen_address') or '') in ('0.0.0.0', '*')
        and str(row.get('connect_address') or '') == '127.0.0.1'
        and int(row.get('listen_port') or 0) == int(row.get('connect_port') or 0)
    ]
    listener_ports = sorted({
        int(row.get('listen_port') or 0) for row in portproxy
    } | {
        int(row.get('connect_port') or 0) for row in portproxy
    })
    listeners = _tcp_listener_rows(listener_ports)
    udp_endpoints = _udp_endpoint_rows(listener_ports)
    enriched_portproxy = []
    for row in portproxy:
        port = int(row.get('listen_port') or 0)
        backend_ok = _has_portproxy_backend_listener(listeners, port)
        row = dict(row)
        row['backend_ok'] = backend_ok
        row['warning'] = None if backend_ok else 'No local TCP listener on 127.0.0.1 for this port.'
        row['udp_detected'] = any(int(endpoint.get('local_port') or 0) == port for endpoint in udp_endpoints)
        enriched_portproxy.append(row)
    return {
        'supported': bool(is_windows() and command_exists('netsh') and command_exists('powershell')),
        'listen_address': '0.0.0.0',
        'connect_address': '127.0.0.1',
        'portproxy': enriched_portproxy,
        'listeners': listeners,
        'udp_endpoints': udp_endpoints,
        'ports': listener_ports,
    }


def ip_helper_status():
    if not is_windows() or not command_exists('powershell'):
        return {'supported': False, 'name': 'iphlpsvc', 'status': 'Unsupported', 'start_type': None, 'running': False}
    try:
        output = subprocess.check_output(
            [
                'powershell',
                '-NoProfile',
                '-Command',
                "Get-Service iphlpsvc | Select-Object Name,@{Name='Status';Expression={$_.Status.ToString()}},@{Name='StartType';Expression={$_.StartType.ToString()}} | ConvertTo-Json -Compress",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=6,
            creationflags=_creationflags(),
        )
        item = json.loads(output or '{}')
    except Exception:
        return {'supported': True, 'name': 'iphlpsvc', 'status': 'Unknown', 'start_type': None, 'running': False}
    status = str(item.get('Status') or '')
    if status == '4':
        status = 'Running'
    elif status == '1':
        status = 'Stopped'
    start_type = item.get('StartType')
    if str(start_type) == '2':
        start_type = 'Automatic'
    elif str(start_type) == '3':
        start_type = 'Manual'
    elif str(start_type) == '4':
        start_type = 'Disabled'
    return {
        'supported': True,
        'name': item.get('Name') or 'iphlpsvc',
        'status': status,
        'start_type': start_type,
        'running': status.lower() == 'running',
    }


def _ip_helper_script(action):
    if action == 'start':
        return """
$ErrorActionPreference = 'Stop'
Set-Service iphlpsvc -StartupType Manual
Start-Service iphlpsvc
"""
    if action == 'stop':
        return """
$ErrorActionPreference = 'Stop'
Stop-Service iphlpsvc -Force
Set-Service iphlpsvc -StartupType Manual
"""
    raise ValueError('Invalid IP Helper action.')


def set_ip_helper_service(action, elevated: bool = True):
    action = str(action or '').strip().lower()
    if action not in ('start', 'stop'):
        raise ValueError('Invalid IP Helper action.')
    current = {'ip_helper': ip_helper_status(), 'port_bindings': port_binding_status()}
    if not is_windows() or not command_exists('powershell'):
        return {'ok': False, 'message': 'IP Helper control is only supported on Windows.', **current}
    script = _ip_helper_script(action)
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            check=True,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=12,
            creationflags=_creationflags(),
        )
        return {
            'ok': True,
            'message': 'IP Helper service is running.' if action == 'start' else 'IP Helper service is stopped.',
            'ip_helper': ip_helper_status(),
            'port_bindings': port_binding_status(),
        }
    except subprocess.CalledProcessError as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc.stderr or '').strip() or 'Failed to update IP Helper service.', **current}
    except Exception as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc), **current}
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        subprocess.Popen(
            ['powershell', '-NoProfile', '-Command', f"Start-Process -Verb RunAs -FilePath powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}')"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
        return {
            'ok': True,
            'pending_elevation': True,
            'message': 'Administrator approval was requested. Confirm the UAC prompt, then refresh this panel.',
            **current,
        }
    except Exception as exc:
        return {'ok': False, 'message': f'Failed to request administrator approval: {exc}', **current}


def _port_binding_apply_script(ports, remove: bool = False):
    normalized = normalize_firewall_ports(ports)
    rows = '\n'.join(f"  {port}" for port in normalized)
    action = 'remove' if remove else 'add'
    return rf"""
$ErrorActionPreference = 'Stop'
$ports = @(
{rows}
)
foreach ($port in $ports) {{
  netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$port | Out-Null
  if ('{action}' -eq 'remove') {{
    continue
  }}
  netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=127.0.0.1 connectport=$port | Out-Null
}}
"""


def _run_elevated_script(script, current):
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        subprocess.Popen(
            ['powershell', '-NoProfile', '-Command', f"Start-Process -Verb RunAs -FilePath powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}')"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
        return {
            'ok': True,
            'pending_elevation': True,
            'message': 'Administrator approval was requested. Confirm the UAC prompt, then refresh this panel.',
            'item': current,
        }
    except Exception as exc:
        return {'ok': False, 'message': f'Failed to request administrator approval: {exc}', 'item': current}


def ensure_port_bindings(ports, elevated: bool = True):
    normalized = normalize_firewall_ports(ports)
    if not normalized:
        return {'ok': False, 'message': 'No ports were provided.', 'item': port_binding_status()}
    if not is_windows() or not command_exists('netsh') or not command_exists('powershell'):
        return {'ok': False, 'message': 'Port binding is only supported on Windows with netsh and PowerShell.', 'item': port_binding_status()}
    current = port_binding_status()
    listeners = _tcp_listener_rows(normalized)
    missing = [port for port in normalized if not _has_portproxy_backend_listener(listeners, port)]
    if missing:
        return {
            'ok': False,
            'message': 'Port binding needs a local TCP listener on 127.0.0.1 first. Not suitable for UDP/discovery-only ports: ' + ', '.join(str(port) for port in missing),
            'item': current,
        }
    script = _port_binding_apply_script(normalized, remove=False)
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            check=True,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=12,
            creationflags=_creationflags(),
        )
        return {'ok': True, 'message': 'Port bindings are enabled.', 'item': port_binding_status()}
    except subprocess.CalledProcessError as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc.stderr or '').strip() or 'Failed to update port bindings.', 'item': current}
    except Exception as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc), 'item': current}
    return _run_elevated_script(script, current)


def remove_port_bindings(ports, elevated: bool = True):
    normalized = normalize_firewall_ports(ports)
    if not normalized:
        return {'ok': False, 'message': 'No ports were provided.', 'item': port_binding_status()}
    current = port_binding_status()
    script = _port_binding_apply_script(normalized, remove=True)
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            check=True,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=12,
            creationflags=_creationflags(),
        )
        return {'ok': True, 'message': 'Port bindings are removed.', 'item': port_binding_status()}
    except subprocess.CalledProcessError as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc.stderr or '').strip() or 'Failed to remove port bindings.', 'item': current}
    except Exception as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc), 'item': current}
    return _run_elevated_script(script, current)


def _firewall_apply_script():
    remote_rows = ', '.join(f"'{addr}'" for addr in normalize_remote_addresses(None))
    return r"""
$ErrorActionPreference = 'Stop'
$remoteAddresses = @(__REMOTE_ADDRESSES__)
$rules = @(
  @{ Name='CLIProxyAPI Dashboard TCP 8765'; Port='8765'; Desc='Allow LAN access to CLIProxyAPI Dashboard panel' },
  @{ Name='CLIProxyAPI Proxy TCP 8317'; Port='8317'; Desc='Allow LAN access to CLIProxyAPI proxy API' }
)
foreach ($rule in $rules) {
  $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
  if ($existing) {
    Set-NetFirewallRule -DisplayName $rule.Name -Enabled True -Direction Inbound -Action Allow -Profile Any
    Set-NetFirewallPortFilter -AssociatedNetFirewallRule $existing -Protocol TCP -LocalPort $rule.Port
    Set-NetFirewallAddressFilter -AssociatedNetFirewallRule $existing -RemoteAddress $remoteAddresses
  } else {
    New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $rule.Port -RemoteAddress $remoteAddresses -Profile Any -Description $rule.Desc | Out-Null
  }
}
""".replace('__REMOTE_ADDRESSES__', remote_rows)


def ensure_firewall_access(elevated: bool = True):
    if not is_windows() or not command_exists('powershell'):
        return {
            'ok': False,
            'message': 'Firewall port allow is only supported on Windows with PowerShell.',
            'firewall': firewall_access_status(),
        }
    current = firewall_access_status()
    if current.get('all_ok'):
        return {'ok': True, 'message': 'Firewall rules are already enabled.', 'firewall': current}
    script = _firewall_apply_script()
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            check=True,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=12,
            creationflags=_creationflags(),
        )
        return {'ok': True, 'message': 'Firewall rules are enabled.', 'firewall': firewall_access_status()}
    except subprocess.CalledProcessError as exc:
        stderr = str(exc.stderr or '').strip()
        if not elevated:
            return {'ok': False, 'message': stderr or 'Failed to update firewall rules.', 'firewall': firewall_access_status()}
    except Exception as exc:
        if not elevated:
            return {'ok': False, 'message': str(exc), 'firewall': firewall_access_status()}

    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        subprocess.Popen(
            ['powershell', '-NoProfile', '-Command', f"Start-Process -Verb RunAs -FilePath powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}')"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
        return {
            'ok': True,
            'pending_elevation': True,
            'message': 'Administrator approval was requested. Confirm the UAC prompt, then refresh this panel.',
            'firewall': firewall_access_status(),
        }
    except Exception as exc:
        return {
            'ok': False,
            'message': f'Failed to request administrator approval: {exc}',
            'firewall': firewall_access_status(),
        }


def stop_pid(pid: int):
    if is_windows() and command_exists('powershell'):
        try:
            subprocess.run(['powershell', '-NoProfile', '-Command', f'Stop-Process -Id {pid} -Force'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def get_process_name(pid: int):
    if is_windows():
        try:
            output = subprocess.check_output(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], text=True, stderr=subprocess.DEVNULL).strip()
            if output.startswith('"'):
                parts = [p.strip('"') for p in output.split(',')]
                if parts and parts[0] != 'INFO: No tasks are running which match the specified criteria.':
                    return parts[0]
        except Exception:
            pass
        return None
    if command_exists('ps'):
        try:
            output = subprocess.check_output(['ps', '-p', str(pid), '-o', 'comm='], text=True, stderr=subprocess.DEVNULL).strip()
            return output or None
        except Exception:
            return None
    return None


_oauth_manager_pid_cache = {'value': None, 'time': 0}

def find_oauth_manager_pid():
    now = time.time()
    if now - _oauth_manager_pid_cache['time'] < 3.0:
        return _oauth_manager_pid_cache['value']
    
    val = _find_oauth_manager_pid_uncached()
    _oauth_manager_pid_cache['value'] = val
    _oauth_manager_pid_cache['time'] = now
    return val

def _find_oauth_manager_pid_uncached():
    if is_windows() and command_exists('powershell'):
        try:
            command = (
                "$needle = 'E:\\U_App\\oauth-manager'; "
                "$p = Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -notlike '*powershell*' -and $_.CommandLine -and $_.CommandLine -like '*switcher.py*--dashboard*' -and $_.CommandLine -like \"*$needle*\" } | "
                "Select-Object -First 1 -ExpandProperty ProcessId; "
                "if($null -ne $p){ Write-Output $p }"
            )
            output = subprocess.check_output(['powershell', '-NoProfile', '-Command', command], text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
            return int(output) if output else None
        except Exception:
            return None
    return None


_openclaw_pid_cache = {'value': None, 'time': 0}

def find_openclaw_gateway_pid():
    now = time.time()
    if now - _openclaw_pid_cache['time'] < 3.0:
        return _openclaw_pid_cache['value']

    val = _find_openclaw_gateway_pid_uncached()
    _openclaw_pid_cache['value'] = val
    _openclaw_pid_cache['time'] = now
    return val

def _find_openclaw_gateway_pid_uncached():
    pid = find_proxy_listener_pid(18789)
    if not pid:
        return None
    name = (get_process_name(pid) or '').lower()
    return pid if name in ('node.exe', 'node') else None


def _kill_pid_tree(pid: int):
    if not pid:
        return False
    if is_windows():
        try:
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            try:
                subprocess.run(['powershell', '-NoProfile', '-Command', f'Stop-Process -Id {int(pid)} -Force'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                return False
    return kill_pid(pid)


def _openclaw_command():
    if OPENCLAW_GATEWAY_CMD.exists():
        if is_windows():
            return ['cmd', '/c', str(OPENCLAW_GATEWAY_CMD)]
        return [str(OPENCLAW_GATEWAY_CMD)]
    if OPENCLAW_CMD.exists():
        if is_windows():
            return ['cmd', '/c', str(OPENCLAW_CMD), 'gateway']
        return [str(OPENCLAW_CMD), 'gateway']
    return ['openclaw', 'gateway']


def start_openclaw_gateway():
    _openclaw_pid_cache['time'] = 0
    with process_lock:
        proc = processes.get('openclaw')
        if process_alive(proc) or find_openclaw_gateway_pid():
            return {'ok': True, 'message': 'OpenClaw gateway is already running.'}

        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            fout = open(OPENCLAW_STDOUT, 'w', encoding='utf-8', errors='ignore')
            ferr = open(OPENCLAW_STDERR, 'w', encoding='utf-8', errors='ignore')
            proc = subprocess.Popen(
                _openclaw_command(),
                cwd=str(OPENCLAW_HOME if OPENCLAW_HOME.exists() else PROXY_ROOT),
                stdout=fout,
                stderr=ferr,
                stdin=subprocess.DEVNULL,
                creationflags=_creationflags(),
            )
            processes['openclaw'] = proc
            _openclaw_pid_cache['value'] = proc.pid
            _openclaw_pid_cache['time'] = time.time()
            return {'ok': True, 'message': 'Started OpenClaw gateway.', 'pid': proc.pid}
        except Exception as exc:
            return {'ok': False, 'message': f'Failed to start OpenClaw gateway: {exc}'}


def stop_openclaw_gateway():
    _openclaw_pid_cache['time'] = 0
    stopped = False
    with process_lock:
        proc = processes.get('openclaw')
        if process_alive(proc):
            stopped = _kill_pid_tree(proc.pid)
            processes['openclaw'] = None

    pid = find_openclaw_gateway_pid()
    if pid:
        stopped = _kill_pid_tree(pid) or stopped
    _openclaw_pid_cache['value'] = None
    _openclaw_pid_cache['time'] = time.time()
    return {'ok': True, 'message': 'Stopped OpenClaw gateway.' if stopped else 'OpenClaw gateway was not running.'}


def restart_openclaw_gateway():
    stop_openclaw_gateway()
    time.sleep(0.4)
    return start_openclaw_gateway()


def _oauth_manager_url():
    port_file = OAUTH_MANAGER_DIR / 'dashboard_port.txt'
    try:
        port = int(port_file.read_text(encoding='utf-8', errors='ignore').strip())
    except Exception:
        port = 1900
    return f'http://127.0.0.1:{port}'


def start_oauth_manager():
    _oauth_manager_pid_cache['time'] = 0
    if not OAUTH_MANAGER_DIR.exists():
        return {'ok': False, 'message': f'OAuth Manager directory was not found: {OAUTH_MANAGER_DIR}'}
    start_bat = OAUTH_MANAGER_DIR / 'start.bat'
    if not start_bat.exists():
        return {'ok': False, 'message': f'start.bat was not found: {start_bat}'}
    
    with process_lock:
        if process_alive(processes.get('oauth_manager')) or find_oauth_manager_pid():
            return {'ok': True, 'message': f'OAuth Manager is already running at {_oauth_manager_url()}.'}
        
        try:
            subprocess.Popen(
                ['cmd', '/c', 'start.bat'],
                cwd=str(OAUTH_MANAGER_DIR),
                creationflags=subprocess.CREATE_NEW_CONSOLE if is_windows() else 0
            )
            return {'ok': True, 'message': f'Started OAuth Manager via start.bat at {_oauth_manager_url()}.'}
        except Exception as exc:
            return {'ok': False, 'message': f'Failed to launch start.bat: {exc}'}


def stop_oauth_manager():
    _oauth_manager_pid_cache['time'] = 0
    stop_bat = OAUTH_MANAGER_DIR / 'stop.bat'
    if not stop_bat.exists():
        return {'ok': False, 'message': f'stop.bat was not found: {stop_bat}'}
    
    with process_lock:
        proc = processes.get('oauth_manager')
        if proc:
            kill_process(proc)
            processes['oauth_manager'] = None
            
    try:
        subprocess.run(
            ['cmd', '/c', 'stop.bat'],
            cwd=str(OAUTH_MANAGER_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags()
        )
        return {'ok': True, 'message': 'Stopped OAuth Manager via stop.bat.'}
    except Exception as exc:
        return {'ok': False, 'message': f'Failed to launch stop.bat: {exc}'}


def read_tail(path, max_chars: int = 6000):
    if not path.exists():
        return ''
    try:
        text = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        try:
            text = path.read_text(encoding='gbk', errors='ignore')
        except Exception:
            return ''
    return text[-max_chars:]


def _normalize_selected_refs(state):
    refs = []
    for ref in (state.get('selected_auth_refs') or []):
        normalized = canonicalize_auth_ref(auth_ref=ref) or str(ref or '').strip()
        if normalized and normalized not in refs:
            refs.append(normalized)
    single = state.get('selected_auth_ref')
    normalized_single = canonicalize_auth_ref(auth_ref=single) or str(single or '').strip()
    if normalized_single and normalized_single not in refs:
        refs.insert(0, normalized_single)
    return refs


def _find_items_by_refs(items, refs):
    wanted = []
    seen = set()
    for ref in refs:
        if not ref or ref in seen:
            continue
        item = next((entry for entry in items if entry.get('id') == ref), None)
        if item:
            wanted.append(item)
            seen.add(ref)
    return wanted


def _summarize_names(items):
    names = [item.get('name') for item in items if item.get('name')]
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    return f'{names[0]} +{len(names) - 1}'


def _same_refs(left, right):
    return set(left or []) == set(right or [])


def detect_lan_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(('8.8.8.8', 80))
            ip = sock.getsockname()[0]
        finally:
            sock.close()
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    return None


def _ip_kind(ip: str) -> str:
    value = str(ip or '').strip()
    if value.startswith(('198.18.', '198.19.')):
        return 'tun'
    if value.startswith('10.') or value.startswith('192.168.'):
        return 'lan'
    match = re.match(r'^172\.(\d+)\.', value)
    if match and 16 <= int(match.group(1)) <= 31:
        return 'lan'
    if value.startswith('100.'):
        return 'carrier'
    return 'public'


def _ip_label(ip: str) -> str:
    kind = _ip_kind(ip)
    if kind == 'tun':
        return 'TUN / 虚拟网卡地址'
    if kind == 'lan':
        return '校园网 / 局域网地址'
    if kind == 'carrier':
        return '运营商内网地址'
    return '公网或其他地址'


def _valid_access_ip(ip: str) -> bool:
    value = str(ip or '').strip()
    if not value or value.startswith(('127.', '0.', '169.254.')):
        return False
    return bool(re.match(r'^\d{1,3}(?:\.\d{1,3}){3}$', value))


_network_ips_cache = {'value': None, 'time': 0}

def detect_network_ips():
    now = time.time()
    if now - _network_ips_cache['time'] < 10.0:
        return _network_ips_cache['value']
    
    val = _detect_network_ips_uncached()
    _network_ips_cache['value'] = val
    _network_ips_cache['time'] = now
    return val

def _detect_network_ips_uncached():
    entries = []
    seen = set()

    def add(ip, source):
        ip = str(ip or '').strip()
        if not _valid_access_ip(ip) or ip in seen:
            return
        seen.add(ip)
        kind = _ip_kind(ip)
        entries.append({
            'ip': ip,
            'kind': kind,
            'label': _ip_label(ip),
            'source': source,
            'base_url': f'http://{ip}:8317',
            'dashboard_url': f'http://{ip}:8765',
            'recommended_for_lan': kind in ('lan', 'public'),
            'is_tun': kind == 'tun',
        })

    default_ip = detect_lan_ip()
    add(default_ip, 'default-route')

    if is_windows():
        try:
            output = subprocess.check_output(
                ['ipconfig'],
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=2,
                creationflags=_creationflags(),
            )
            for match in re.finditer(r'IPv4[^\r\n:]*:\s*([0-9.]+)', output):
                add(match.group(1), 'ipconfig')
        except Exception:
            pass
    else:
        try:
            host = socket.gethostname()
            for info in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM):
                add(info[4][0], 'hostname')
        except Exception:
            pass

    entries.sort(key=lambda item: (
        0 if item.get('kind') == 'lan' else 1 if item.get('kind') == 'public' else 2 if item.get('kind') == 'tun' else 3,
        0 if item.get('source') == 'default-route' else 1,
        item.get('ip') or '',
    ))
    return entries


def recommend_external_ip(network_ips):
    for item in network_ips or []:
        if item.get('recommended_for_lan'):
            return item
    for item in network_ips or []:
        if item.get('ip'):
            return item
    return None


def probe_socket_stack():
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        return None
    except OSError as exc:
        win_error = getattr(exc, 'winerror', None)
        if win_error == 10106:
            return 'Local socket stack is unavailable (Winsock WinError 10106). Run an elevated "netsh winsock reset", then reboot Windows.'
        return f'Local socket stack is unavailable: {exc}'
    except Exception as exc:
        return f'Local socket stack is unavailable: {exc}'
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def start_device_login():
    if not _cli_binary_ready():
        return {'ok': False, 'message': _cli_unavailable_message()}
    with process_lock:
        if process_alive(processes.get('device_login')):
            return {'ok': True, 'message': 'Device login is already running.'}
        DEVICE_LOGIN_STDOUT.parent.mkdir(parents=True, exist_ok=True)
        stdout = open(DEVICE_LOGIN_STDOUT, 'w', encoding='utf-8', errors='ignore')
        stderr = open(DEVICE_LOGIN_STDERR, 'w', encoding='utf-8', errors='ignore')
        proc = subprocess.Popen([str(CLI_EXE), '-codex-device-login', '-config', str(BASE_CONFIG)], cwd=str(PROJECT_ROOT), stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, creationflags=_creationflags())
        processes['device_login'] = proc
        return {'ok': True, 'message': 'Started Codex device login. Check logs for device URL and code.'}


def stop_device_login():
    with process_lock:
        stopped = kill_process(processes.get('device_login'))
        processes['device_login'] = None
    return {'ok': True, 'message': 'Stopped device login.' if stopped else 'Device login was not running.'}


def start_proxy():
    if not _cli_binary_ready():
        return {'ok': False, 'message': _cli_unavailable_message()}
    state = load_state()
    auth_files = list_auth_files()
    has_active_auth_files = bool(auth_files)
    if not has_active_auth_files:
        return {'ok': False, 'message': 'storage/auth is empty. Put auth JSON files into storage/auth/<provider>/ first.'}
    bind_host = get_proxy_bind_host(state)
    access_api_key = get_proxy_api_key(state)
    socket_issue = probe_socket_stack()
    if socket_issue:
        return {'ok': False, 'message': socket_issue}
    with process_lock:
        if process_alive(processes.get('proxy')):
            return {'ok': True, 'message': 'RelayX is already running.'}
        listener_pid = find_proxy_listener_pid()
        if listener_pid:
            process_name = get_process_name(listener_pid)
            normalized_name = str(process_name or '').strip().lower()
            if normalized_name in _managed_proxy_process_names():
                if not stop_pid(listener_pid):
                    return {'ok': False, 'message': f'Port 8317 is occupied by existing RelayX (PID {listener_pid}) and could not be stopped.'}
                time.sleep(0.5)
            else:
                label = process_name or f'PID {listener_pid}'
                return {'ok': False, 'message': f'Port 8317 is occupied by {label}. Please stop it first.'}
        try:
            build_runtime_config(
                bind_host=bind_host,
                access_api_keys=[access_api_key],
                state=state,
            )
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}
        cmd = [str(CLI_EXE), '-config', str(RUNTIME_CONFIG)]
        if state.get('local_model'):
            cmd.append('--local-model')
        proxy_env = {}
        try:
            from backend.proxy_env import build_proxy_env_dict
            proxy_env = build_proxy_env_dict(state)
        except Exception:
            pass
        merged_env = os.environ.copy()
        merged_env.update(proxy_env)
        stdout = open(PROXY_STDOUT, 'a', encoding='utf-8', errors='ignore')
        stderr = open(PROXY_STDERR, 'a', encoding='utf-8', errors='ignore')
        proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, creationflags=_creationflags(), env=merged_env)
        processes['proxy'] = proc
    selected_items = auth_files
    state['selected_auth_refs'] = [item.get('id') for item in selected_items]
    state['selected_auths'] = [item.get('name') for item in selected_items]
    state['selected_auth_ref'] = state['selected_auth_refs'][0] if state['selected_auth_refs'] else None
    state['selected_auth'] = state['selected_auths'][0] if state['selected_auths'] else None
    state['applied_auth_refs'] = list(state['selected_auth_refs'])
    state['applied_auths'] = list(state['selected_auths'])
    state['applied_auth_ref'] = state['applied_auth_refs'][0] if state['applied_auth_refs'] else None
    state['applied_auth'] = state['applied_auths'][0] if state['applied_auths'] else None
    state['last_proxy_bind_host'] = bind_host
    state['last_proxy_api_key'] = access_api_key
    state['applied_route_strategy'] = normalize_route_strategy(state.get('route_strategy'))
    save_state(state)
    return {'ok': True, 'message': f'Started RelayX with storage/auth account files: {len(selected_items)} active.'}


def stop_proxy():
    with process_lock:
        proc = processes.get('proxy')
        stopped = kill_process(proc)
        processes['proxy'] = None
    if not stopped:
        listener_pid = find_proxy_listener_pid()
        if listener_pid:
            stopped = stop_pid(listener_pid)
    state = load_state()
    state['applied_auth'] = None
    state['applied_auth_ref'] = None
    state['applied_auths'] = []
    state['applied_auth_refs'] = []
    state['last_proxy_bind_host'] = None
    state['last_proxy_api_key'] = None
    save_state(state)
    return {'ok': True, 'message': 'Stopped RelayX.' if stopped else 'RelayX was not running.'}


def restart_proxy():
    stop_proxy()
    time.sleep(0.4)
    return start_proxy()


def media_proxy_config_path():
    return MEDIA_PROXY_ROOT / 'config.example.json'


def wait_for_media_proxy_ready(timeout_seconds: float = 60.0):
    deadline = time.monotonic() + timeout_seconds
    port = media_proxy_port()
    while time.monotonic() < deadline:
        if find_proxy_listener_pid(port):
            return True
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def start_media_proxy():
    if not MEDIA_PROXY_ROOT.exists():
        return {'ok': False, 'message': f'Media proxy directory was not found: {MEDIA_PROXY_ROOT}'}
    if not media_proxy_config_path().exists():
        return {'ok': False, 'message': f'Media proxy config was not found: {media_proxy_config_path()}'}
    if not command_exists('go'):
        return {'ok': False, 'message': 'Go runtime was not found in PATH. Install Go or build CLIProxyAPI-MediaProxy first.'}
    auth_files = list_auth_files()
    if not auth_files:
        return {'ok': False, 'message': 'storage/auth is empty. Add Agnes auth files before starting media proxy.'}
    with process_lock:
        if process_alive(processes.get('media_proxy')) or find_proxy_listener_pid(media_proxy_port()):
            return {'ok': True, 'message': 'Media proxy is already running.'}
        MEDIA_PROXY_STDOUT.parent.mkdir(parents=True, exist_ok=True)
        stdout = open(MEDIA_PROXY_STDOUT, 'a', encoding='utf-8', errors='ignore')
        stderr = open(MEDIA_PROXY_STDERR, 'a', encoding='utf-8', errors='ignore')
        proc = subprocess.Popen(
            ['go', 'run', '.', '-config', str(media_proxy_config_path())],
            cwd=str(MEDIA_PROXY_ROOT),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
        processes['media_proxy'] = proc
    if wait_for_media_proxy_ready():
        return {'ok': True, 'message': 'Started media proxy on http://127.0.0.1:8320.', 'pid': proc.pid}
    if proc.poll() is not None:
        return {'ok': False, 'message': f'Media proxy exited during startup. Check {MEDIA_PROXY_STDERR}.'}
    return {'ok': False, 'message': 'Media proxy start command was sent, but port 8320 did not become ready in time.'}


def stop_media_proxy():
    with process_lock:
        proc = processes.get('media_proxy')
        stopped = kill_process(proc)
        processes['media_proxy'] = None
    if not stopped:
        listener_pid = find_proxy_listener_pid(media_proxy_port())
        if listener_pid:
            stopped = stop_pid(listener_pid)
    return {'ok': True, 'message': 'Stopped media proxy.' if stopped else 'Media proxy was not running.'}


def restart_media_proxy():
    stop_media_proxy()
    time.sleep(0.4)
    return start_media_proxy()


def current_status(include_logs: bool = True):
    state = load_state()
    auth_files = list_auth_files()

    selected_items = auth_files
    applied_items = auth_files if process_alive(processes.get('proxy')) or find_proxy_listener_pid() else []
    selected_refs = [item.get('id') for item in selected_items if item.get('id')]
    applied_refs = [item.get('id') for item in applied_items if item.get('id')]

    selected_display = f'{len(selected_items)} active file(s)'
    applied_display = f'{len(applied_items)} active file(s)' if applied_items else None

    tracked_proxy_running = process_alive(processes.get('proxy'))
    tracked_media_proxy_running = process_alive(processes.get('media_proxy'))
    tracked_oauth_manager_running = process_alive(processes.get('oauth_manager'))
    tracked_openclaw_proc = processes.get('openclaw')
    tracked_openclaw_running = process_alive(tracked_openclaw_proc)
    oauth_manager_pid = find_oauth_manager_pid()
    oauth_manager_running = bool(tracked_oauth_manager_running or oauth_manager_pid)
    openclaw_pid = tracked_openclaw_proc.pid if tracked_openclaw_running else find_openclaw_gateway_pid()
    openclaw_running = bool(tracked_openclaw_running or openclaw_pid)
    listener_pid = find_proxy_listener_pid()
    media_proxy_pid = processes.get('media_proxy').pid if tracked_media_proxy_running else find_proxy_listener_pid(media_proxy_port())
    listener_process_name = get_process_name(listener_pid) if listener_pid else None
    listener_is_proxy = bool(listener_pid and listener_process_name and listener_process_name.lower() == 'cli-proxy-api.exe')
    proxy_running = bool(tracked_proxy_running or listener_is_proxy)
    bind_host = get_proxy_bind_host(state)
    effective_api_key = get_proxy_api_key(state)
    current_route_strategy = normalize_route_strategy(state.get('route_strategy'))
    applied_route_strategy = normalize_route_strategy(state.get('applied_route_strategy'))
    restart_required = bool(
        proxy_running and (
            False
            or bind_host != state.get('last_proxy_bind_host')
            or effective_api_key != state.get('last_proxy_api_key')
            or current_route_strategy != applied_route_strategy
        )
    )
    exposure_enabled = bool(state.get('exposure_enabled'))
    lan_ip = detect_lan_ip()
    network_ips = detect_network_ips()
    recommended_external = recommend_external_ip(network_ips)
    socket_issue = probe_socket_stack()
    local_proxy_url = 'http://127.0.0.1:8317'
    external_ip = (recommended_external or {}).get('ip') or lan_ip
    exposure_url = f'http://{external_ip}:8317' if exposure_enabled and external_ip else None
    dashboard_port = get_dashboard_port()
    dashboard_bind_host = get_dashboard_bind_host()
    dashboard_remote_accessible = dashboard_allows_remote_access(dashboard_port)
    dashboard_lan_url = f'http://{external_ip}:{dashboard_port}' if dashboard_remote_accessible and external_ip else None

    status = {
        'selected_auth': selected_display,
        'selected_auth_ref': selected_refs[0] if selected_refs else None,
        'selected_auths': [item.get('name') for item in selected_items],
        'selected_auth_refs': [item.get('id') for item in selected_items],
        'applied_auth': applied_display,
        'applied_auth_ref': applied_refs[0] if applied_refs else None,
        'applied_auths': [item.get('name') for item in applied_items],
        'applied_auth_refs': [item.get('id') for item in applied_items],
        'selected_provider': ', '.join(sorted({item.get('provider') for item in selected_items if item.get('provider')})) or None,
        'selected_providers': [item.get('provider') for item in selected_items if item.get('provider')],
        'applied_provider': ', '.join(sorted({item.get('provider') for item in applied_items if item.get('provider')})) or None,
        'applied_providers': [item.get('provider') for item in applied_items if item.get('provider')],
        'restart_required': restart_required,
        'device_login_running': process_alive(processes.get('device_login')),
        'proxy_running': proxy_running,
        'proxy_pid': listener_pid,
        'proxy_managed_by_dashboard': tracked_proxy_running,
        'media_proxy_running': bool(tracked_media_proxy_running or media_proxy_pid),
        'media_proxy_pid': media_proxy_pid,
        'media_proxy_url': f'http://127.0.0.1:{media_proxy_port()}',
        'proxy_url': local_proxy_url,
        'local_proxy_url': local_proxy_url,
        'exposure_url': exposure_url,
        'bind_host': bind_host,
        'exposure_enabled': exposure_enabled,
        'api_key': effective_api_key,
        'lan_ip': external_ip,
        'default_route_ip': lan_ip,
        'network_ips': network_ips,
        'recommended_external_ip': recommended_external,
        'dashboard_bind_host': dashboard_bind_host,
        'dashboard_port': dashboard_port,
        'dashboard_remote_accessible': dashboard_remote_accessible,
        'dashboard_lan_url': dashboard_lan_url,
        'proxy_health_issue': socket_issue,
        'oauth_manager_running': oauth_manager_running,
        'oauth_manager_pid': oauth_manager_pid,
        'oauth_manager_url': _oauth_manager_url(),
        'openclaw_running': openclaw_running,
        'openclaw_pid': openclaw_pid,
        'auth_files_count': len(auth_files),
        'tunnel_running': is_cloudflared_running(),
        'dashboard_root': str(DASHBOARD_ROOT),
        'proxy_root': str(PROXY_ROOT),
        'app_dir': str(PROXY_ROOT),
        'storage_dir': str(STORAGE_DIR),
        'cli_exe': str(CLI_EXE),
        'base_config': str(BASE_CONFIG),
        'runtime_variant': RUNTIME_VARIANT,
        'runtime_config': str(RUNTIME_CONFIG),
        'active_auth_dir': str(POOL_AUTH_DIR),
        'auth_pool_dir': str(POOL_AUTH_DIR),
    }
    if include_logs:
        status.update({
            'oauth_manager_stdout': read_tail(OAUTH_MANAGER_STDOUT),
            'oauth_manager_stderr': read_tail(OAUTH_MANAGER_STDERR),
            'openclaw_stdout': read_tail(OPENCLAW_STDOUT),
            'openclaw_stderr': read_tail(OPENCLAW_STDERR),
            'device_login_stdout': read_tail(DEVICE_LOGIN_STDOUT),
            'device_login_stderr': read_tail(DEVICE_LOGIN_STDERR),
            'proxy_stdout': read_tail(PROXY_STDOUT),
            'proxy_stderr': read_tail(PROXY_STDERR),
            'media_proxy_stdout': read_tail(MEDIA_PROXY_STDOUT),
            'media_proxy_stderr': read_tail(MEDIA_PROXY_STDERR),
        })
    return status


def shutdown_all():
    with process_lock:
        for key in list(processes):
            kill_process(processes.get(key))
            processes[key] = None
        for key in list(tool_processes):
            kill_process(tool_processes.get(key))
            tool_processes.pop(key, None)


def start_project():
    status = current_status()
    if status.get('proxy_running'):
        return {
            'ok': True,
            'message': 'Project is already running.',
            'project_running': True,
            'proxy_running': True,
        }
    result = start_proxy()
    return {
        **result,
        'project_running': bool(result.get('ok')),
        'proxy_running': bool(result.get('ok')),
    }


def stop_project():
    proxy_result = stop_proxy()
    device_result = stop_device_login()
    shutdown_all()
    return {
        'ok': True,
        'message': 'Project stopped. Proxy, login processes, and external tools were shut down.',
        'project_running': False,
        'proxy': proxy_result,
        'device_login': device_result,
    }


_cloudflared_running_cache = {'value': False, 'time': 0}

def is_cloudflared_running():
    now = time.time()
    if now - _cloudflared_running_cache['time'] < 2.0:
        return _cloudflared_running_cache['value']
    
    val = _is_cloudflared_running_uncached()
    _cloudflared_running_cache['value'] = val
    _cloudflared_running_cache['time'] = now
    return val

def _is_cloudflared_running_uncached():
    if is_windows():
        try:
            output = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq cloudflared.exe', '/FO', 'CSV', '/NH'], text=True, stderr=subprocess.DEVNULL)
            return 'cloudflared.exe' in output.lower()
        except Exception:
            return False
    else:
        try:
            output = subprocess.check_output(['pgrep', 'cloudflared'], text=True, stderr=subprocess.DEVNULL)
            return bool(output.strip())
        except Exception:
            return False

def start_cloudflared_tunnel():
    token = os.environ.get('CLOUDFLARED_TUNNEL_TOKEN', '').strip()
    if not token:
        return {'ok': False, 'message': 'Cloudflared tunnel token is not configured in .env file (CLOUDFLARED_TUNNEL_TOKEN).'}
    if is_cloudflared_running():
        return {'ok': True, 'message': 'Cloudflared tunnel is already running.'}
    if not is_windows():
        return {'ok': False, 'message': 'Starting cloudflared tunnel is only supported on Windows.'}
    
    cmd_str = f"cloudflared tunnel run --token {token}"
    script = f"""
$ErrorActionPreference = 'Stop'
Start-Process -Verb RunAs -FilePath powershell -ArgumentList '-NoProfile', '-WindowStyle', 'Hidden', '-Command', '{cmd_str}'
"""
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        subprocess.Popen(
            ['powershell', '-NoProfile', '-Command', f"Start-Process -Verb RunAs -FilePath powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}')"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
        return {'ok': True, 'message': 'Cloudflared tunnel start command sent with Admin rights.'}
    except Exception as exc:
        return {'ok': False, 'message': f'Failed to launch tunnel command: {exc}'}

def stop_cloudflared_tunnel():
    if not is_cloudflared_running():
        return {'ok': True, 'message': 'Cloudflared tunnel is not running.'}
    if not is_windows():
        return {'ok': False, 'message': 'Stopping cloudflared tunnel is only supported on Windows.'}
    
    script = """
$ErrorActionPreference = 'Stop'
Stop-Process -Name cloudflared -Force
"""
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        subprocess.Popen(
            ['powershell', '-NoProfile', '-Command', f"Start-Process -Verb RunAs -FilePath powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}')"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags(),
        )
        return {'ok': True, 'message': 'Cloudflared tunnel stop command sent with Admin rights.'}
    except Exception as exc:
        return {'ok': False, 'message': f'Failed to launch stop command: {exc}'}
