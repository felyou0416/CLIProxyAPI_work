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
import shutil
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
    ACCESS_GATEWAY_ROOT,
    ACCESS_GATEWAY_BINARY,
    DASHBOARD_ROOT,
    STORAGE_DIR,
    RUNTIME_DIR,
    LOGS_DIR,
    MEDIA_PROXY_STDOUT,
    MEDIA_PROXY_STDERR,
    GROK2API_ROOT,
    GROK2API_STDOUT,
    GROK2API_STDERR,
    GROK2API_FRONTEND_STDOUT,
    GROK2API_FRONTEND_STDERR,
    ACCESS_GATEWAY_STDOUT,
    ACCESS_GATEWAY_STDERR,
    RUNTIME_VARIANT,
    POOL_AUTH_DIR,
)
from backend.auth import build_runtime_config, list_auth_files, build_auth_ref, canonicalize_auth_ref
from backend.state import load_state, save_state, get_proxy_bind_host, get_proxy_api_key, normalize_route_strategy
from backend.runtime_env import command_exists, is_windows, cli_binary_hint

process_lock = threading.Lock()
# Proxy start can take many seconds (config build + port wait). Keep that work
# OUTSIDE process_lock so /api/status and other dashboard APIs stay responsive.
# This flag only prevents concurrent start/restart of the same proxy stack.
_proxy_start_state = {
    'starting': False,
    'restarting': False,
    'started_at': 0.0,
}


def _set_proxy_starting(starting: bool):
    with process_lock:
        _proxy_start_state['starting'] = starting
        if starting:
            _proxy_start_state['started_at'] = time.time()


def _set_proxy_restarting(restarting: bool):
    with process_lock:
        _proxy_start_state['restarting'] = restarting


def get_process_name(pid):
    """Return the process name for a given PID using psutil, or None if unavailable."""
    try:
        return psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None
processes = {
    'device_login': None,
    'proxy': None,
    'access_gateway': None,
    'media_proxy': None,
    'oauth_manager': None,
    'openclaw': None,
    'create_grok': None,
    'chat77': None,
    'grok2api': None,
    'grok2api_frontend': None,
}
tool_processes: dict = {}
tool_states: dict = {}
DEFAULT_TRUSTED_REMOTE_ADDRESSES = ['fd7a:115c:a1e0::9e39:c580', '100.89.197.128']
OAUTH_MANAGER_DIR = Path(r'E:\U_App\oauth-manager')
OAUTH_MANAGER_SWITCHER = OAUTH_MANAGER_DIR / 'switcher.py'
OAUTH_MANAGER_RUN_DIR = OAUTH_MANAGER_DIR / 'run'
OAUTH_MANAGER_PID_FILE = OAUTH_MANAGER_RUN_DIR / 'dashboard.pid'
OAUTH_MANAGER_PORT_FILE = OAUTH_MANAGER_RUN_DIR / 'dashboard_port.txt'
OAUTH_MANAGER_LEGACY_PORT_FILE = OAUTH_MANAGER_DIR / 'dashboard_port.txt'
OAUTH_MANAGER_STDOUT = OAUTH_MANAGER_DIR / 'logs' / 'dashboard.stdout.log'
OAUTH_MANAGER_STDERR = OAUTH_MANAGER_DIR / 'logs' / 'dashboard.stderr.log'
OAUTH_MANAGER_DEFAULT_PORT = 1900
# Grok 批量注册面板（grok-register-mint Web UI，默认 :3780）
CREATE_GROK_DIR = Path(r'E:\U_App\grok-register-mint')
CREATE_GROK_ENTRY = CREATE_GROK_DIR / 'web_ui.py'
CREATE_GROK_DEFAULT_PORT = 3780
CREATE_GROK_STDOUT = LOGS_DIR / 'create-grok.stdout.log'
CREATE_GROK_STDERR = LOGS_DIR / 'create-grok.stderr.log'

# 77chat 面板（默认 :90）
CHAT77_DIR = Path(r'E:\Cloud\77chat-90')
CHAT77_SERVER = CHAT77_DIR / 'src' / 'server' / 'index.js'
CHAT77_DEFAULT_PORT = 90
CHAT77_STDOUT = LOGS_DIR / 'chat77.stdout.log'
CHAT77_STDERR = LOGS_DIR / 'chat77.stderr.log'
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
    return {'cli-proxy-api.exe', 'cliproxyapi.exe', 'cli-proxy-api', 'cliproxyapi', 'cli-access-gateway.exe', 'cli-access-gateway'}


def core_proxy_port():
    return 8318


def media_proxy_port():
    return 8320


def grok2api_port():
    return 8000


def grok2api_frontend_port():
    return 5173


def wait_for_listener(port: int, proc=None, timeout_seconds: float = 30.0):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        if find_proxy_listener_pid(port):
            return True
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.2)
    return False


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


def kill_process(proc, timeout=1.0):
    if not process_alive(proc):
        return False
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
        return True
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=timeout)
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


# Dashboard self-restart guards (process-local + on-disk).
_DASHBOARD_LIFECYCLE_LOCK = threading.Lock()
_DASHBOARD_EXIT_SCHEDULED = False
_DASHBOARD_RESTART_SCHEDULED = False
_DASHBOARD_RESTART_COOLDOWN_SECONDS = 20.0
_DASHBOARD_RELAUNCH_WAIT_SECONDS = 30.0
_DASHBOARD_RESTART_STAMP_FILE = None  # resolved lazily under RUNTIME_DIR


def _dashboard_restart_stamp_path() -> Path:
    global _DASHBOARD_RESTART_STAMP_FILE
    if _DASHBOARD_RESTART_STAMP_FILE is None:
        _DASHBOARD_RESTART_STAMP_FILE = Path(RUNTIME_DIR) / 'dashboard-restart.stamp'
    return _DASHBOARD_RESTART_STAMP_FILE


def _dashboard_relaunch_log_path() -> Path:
    return Path(LOGS_DIR) / 'dashboard.relaunch.log'


def _read_dashboard_restart_stamp() -> dict | None:
    path = _dashboard_restart_stamp_path()
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_dashboard_restart_stamp(payload: dict) -> None:
    path = _dashboard_restart_stamp_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _clear_dashboard_restart_stamp(token: str | None = None) -> None:
    path = _dashboard_restart_stamp_path()
    try:
        if not path.exists():
            return
        if token:
            current = _read_dashboard_restart_stamp() or {}
            if str(current.get('token') or '') not in ('', str(token)):
                return
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _dashboard_restart_in_cooldown(now: float | None = None) -> dict | None:
    """Return a reject payload if another restart was scheduled too recently."""
    stamp = _read_dashboard_restart_stamp()
    if not stamp:
        return None
    now = float(now if now is not None else time.time())
    scheduled_at = float(stamp.get('scheduled_at') or 0.0)
    if scheduled_at <= 0:
        return None
    age = now - scheduled_at
    if age < 0:
        # Clock skew / corrupt stamp — clear and allow.
        _clear_dashboard_restart_stamp()
        return None
    if age >= _DASHBOARD_RESTART_COOLDOWN_SECONDS:
        # Stale stamp from a previous attempt; do not block forever.
        if age >= max(_DASHBOARD_RESTART_COOLDOWN_SECONDS * 3, 60.0):
            _clear_dashboard_restart_stamp()
        return None
    remaining = max(1, int(_DASHBOARD_RESTART_COOLDOWN_SECONDS - age))
    return {
        'ok': False,
        'message': f'Dashboard restart already in progress. Retry in ~{remaining}s.',
        'cooldown_seconds': remaining,
        'token': stamp.get('token'),
    }


def stop_dashboard_panel(delay_seconds: float = 0.5):
    global _DASHBOARD_EXIT_SCHEDULED
    with _DASHBOARD_LIFECYCLE_LOCK:
        if _DASHBOARD_EXIT_SCHEDULED:
            return {'ok': True, 'message': 'Dashboard panel stop already scheduled.'}
        _DASHBOARD_EXIT_SCHEDULED = True

    def _stop_later():
        time.sleep(max(0.15, float(delay_seconds or 0.5)))
        os._exit(0)

    threading.Thread(target=_stop_later, name='dashboard-stop', daemon=True).start()
    return {'ok': True, 'message': 'Dashboard panel is stopping.'}


def _dashboard_start_script() -> Path | None:
    ps_script = DASHBOARD_ROOT / 'start_dashboard.ps1'
    if ps_script.exists():
        return ps_script
    bat_script = DASHBOARD_ROOT / 'start_dashboard.bat'
    if bat_script.exists():
        return bat_script
    return None


def _dashboard_relaunch_creationflags() -> int:
    if not is_windows():
        return 0
    flags = 0
    # NOTE: Do NOT use DETACHED_PROCESS (0x8). With PowerShell -File it often exits
    # immediately (code 0) and never runs the waiter — no relaunch log, panel stays dead.
    # Windows children normally survive parent os._exit without DETACHED_PROCESS.
    flags |= int(getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) or 0)
    flags |= int(getattr(subprocess, 'CREATE_NO_WINDOW', 0) or 0)
    # Break out of Job Objects (Electron/service hosts) that would kill children with parent.
    flags |= 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
    return flags


def _resolve_powershell_exe() -> str:
    """Prefer absolute powershell.exe — bare 'powershell' can fail under detached PATH."""
    candidates = []
    system_root = os.environ.get('SystemRoot') or os.environ.get('WINDIR') or r'C:\Windows'
    candidates.append(str(Path(system_root) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'))
    which = shutil.which('powershell.exe') or shutil.which('powershell')
    if which:
        candidates.append(which)
    for path in candidates:
        try:
            if path and Path(path).exists():
                return path
        except Exception:
            continue
    return 'powershell.exe'


def _spawn_dashboard_relauncher(delay_seconds: float = 0.8, token: str = '') -> dict:
    """Spawn a detached one-shot waiter that starts Dashboard after this process dies.

    Guards:
    - waits for the current PID to exit (hard deadline, no infinite loop)
    - never force-starts while the old process is still alive (avoids the
      start-script "already healthy → exit" short-circuit that leaves the panel dead)
    - stamp token is one-shot; relauncher clears it and exits after a single attempt
    - Windows: write a real .ps1 file (EncodedCommand + DETACHED often dies silently)
    """
    script = _dashboard_start_script()
    if script is None:
        return {
            'ok': False,
            'message': f'Dashboard start script was not found under {DASHBOARD_ROOT}.',
        }

    port = get_dashboard_port()
    pid = os.getpid()
    root = str(DASHBOARD_ROOT)
    settle_ms = int(max(0.2, float(delay_seconds or 0.8)) * 1000)
    wait_budget = int(_DASHBOARD_RELAUNCH_WAIT_SECONDS)
    log_dir = Path(LOGS_DIR)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    relaunch_log = _dashboard_relaunch_log_path()
    stamp_path = str(_dashboard_restart_stamp_path())
    token = str(token or f'{pid}-{int(time.time())}')

    if is_windows():
        # Persist one-shot waiter as a file. EncodedCommand under DETACHED_PROCESS
        # often never runs (no log, no start) — disk script + -File is reliable.
        waiter_path = log_dir / f'dashboard-relaunch-{token}.ps1'
        launcher_stdout = log_dir / 'dashboard.relaunch.launcher.stdout.log'
        launcher_stderr = log_dir / 'dashboard.relaunch.launcher.stderr.log'
        ps = f"""
$ErrorActionPreference = 'Continue'
$log = {json.dumps(str(relaunch_log))}
$stamp = {json.dumps(stamp_path)}
$token = {json.dumps(token)}
$targetPid = {int(pid)}
$port = {int(port)}
$selfScript = {json.dumps(str(waiter_path))}
function Write-RelaunchLog([string]$msg) {{
  $line = "$((Get-Date).ToString('s')) [$token] $msg"
  try {{ Add-Content -LiteralPath $log -Value $line -Encoding utf8 }} catch {{}}
}}
function Clear-RestartStamp {{
  try {{
    if (Test-Path -LiteralPath $stamp) {{
      $raw = Get-Content -LiteralPath $stamp -Raw -ErrorAction SilentlyContinue
      if (-not $raw -or $raw -match [regex]::Escape($token)) {{
        Remove-Item -LiteralPath $stamp -Force -ErrorAction SilentlyContinue
      }}
    }}
  }} catch {{}}
}}
function Test-PidAlive([int]$ProcessId) {{
  try {{
    $p = Get-Process -Id $ProcessId -ErrorAction Stop
    return ($null -ne $p)
  }} catch {{
    return $false
  }}
}}
function Remove-SelfScript {{
  try {{
    if ($selfScript -and (Test-Path -LiteralPath $selfScript)) {{
      Remove-Item -LiteralPath $selfScript -Force -ErrorAction SilentlyContinue
    }}
  }} catch {{}}
}}
try {{
  Write-RelaunchLog "relauncher started; waiting for pid=$targetPid port=$port (max {wait_budget}s)"
  $deadline = (Get-Date).AddSeconds({wait_budget})
  $released = $false
  while ((Get-Date) -lt $deadline) {{
    if (-not (Test-PidAlive $targetPid)) {{
      $released = $true
      break
    }}
    Start-Sleep -Milliseconds 250
  }}
  if (-not $released) {{
    Write-RelaunchLog "timed out waiting for pid=$targetPid; aborting relaunch (no force-start while old process is alive)"
    Clear-RestartStamp
    Remove-SelfScript
    exit 2
  }}
  Write-RelaunchLog "pid=$targetPid exited; settle {settle_ms}ms then start"
  Start-Sleep -Milliseconds {settle_ms}
  # If something else already revived the panel, do not start a second copy.
  try {{
    $req = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:$port/")
    $req.Method = 'GET'
    $req.Timeout = 800
    $req.ReadWriteTimeout = 800
    $req.Proxy = [System.Net.GlobalProxySelection]::GetEmptyWebProxy()
    $req.KeepAlive = $false
    try {{
      $resp = $req.GetResponse()
      $code = [int]$resp.StatusCode
      $resp.Close()
      if ($code -ge 200 -and $code -lt 500) {{
        Write-RelaunchLog "port $port already healthy after exit; skip start"
        Clear-RestartStamp
        Remove-SelfScript
        exit 0
      }}
    }} catch [System.Net.WebException] {{
      $resp = $_.Exception.Response
      if ($null -ne $resp) {{
        $code = [int]$resp.StatusCode
        $resp.Close()
        if ($code -ge 200 -and $code -lt 500) {{
          Write-RelaunchLog "port $port already answering ($code); skip start"
          Clear-RestartStamp
          Remove-SelfScript
          exit 0
        }}
      }}
    }}
  }} catch {{}}
  $startScript = {json.dumps(str(script))}
  $cwd = {json.dumps(root)}
  $psExe = {json.dumps(_resolve_powershell_exe())}
  try {{
    if ($startScript.ToLower().EndsWith('.ps1')) {{
      $p = Start-Process -FilePath $psExe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$startScript) -WorkingDirectory $cwd -WindowStyle Hidden -PassThru
    }} else {{
      $p = Start-Process -FilePath $startScript -WorkingDirectory $cwd -WindowStyle Hidden -PassThru
    }}
    Write-RelaunchLog "start script launched pid=$($p.Id) via $startScript"
    Clear-RestartStamp
    Remove-SelfScript
    exit 0
  }} catch {{
    Write-RelaunchLog "failed to launch start script: $($_.Exception.Message)"
    Clear-RestartStamp
    Remove-SelfScript
    exit 1
  }}
}} catch {{
  Write-RelaunchLog "relauncher crashed: $($_.Exception.Message)"
  Clear-RestartStamp
  Remove-SelfScript
  exit 1
}}
""".strip()
        try:
            waiter_path.write_text(ps + '\n', encoding='utf-8')
        except Exception as exc:
            return {
                'ok': False,
                'message': f'Failed to write dashboard relauncher script: {exc}',
            }

        ps_exe = _resolve_powershell_exe()
        cmd = [
            ps_exe,
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-WindowStyle', 'Hidden',
            '-File', str(waiter_path),
        ]
        try:
            fout = open(launcher_stdout, 'a', encoding='utf-8', errors='ignore')
            ferr = open(launcher_stderr, 'a', encoding='utf-8', errors='ignore')
            try:
                fout.write(f'\n==== schedule {time.strftime("%Y-%m-%d %H:%M:%S")} token={token} pid={pid} ====\n')
                fout.flush()
            except Exception:
                pass
            proc = subprocess.Popen(
                cmd,
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=fout,
                stderr=ferr,
                # Windows: keep handles open so the child can write logs; close_fds=True
                # + DETACHED has been observed to drop the relauncher before it logs.
                close_fds=False,
                creationflags=_dashboard_relaunch_creationflags(),
            )
        except Exception as exc:
            try:
                waiter_path.unlink(missing_ok=True)
            except Exception:
                pass
            return {
                'ok': False,
                'message': f'Failed to schedule dashboard relaunch: {exc}',
            }

        # Confirm the waiter process actually started (not immediately dead).
        time.sleep(0.15)
        if proc.poll() is not None:
            err_tail = ''
            try:
                err_tail = launcher_stderr.read_text(encoding='utf-8', errors='ignore')[-400:]
            except Exception:
                pass
            try:
                waiter_path.unlink(missing_ok=True)
            except Exception:
                pass
            message = f'Dashboard relauncher exited immediately (code {proc.returncode}).'
            if err_tail.strip():
                message = f'{message} {err_tail.strip()}'
            return {'ok': False, 'message': message}

        return {
            'ok': True,
            'message': 'Dashboard panel is restarting.',
            'relaunch_log': str(relaunch_log),
            'port': port,
            'pid': pid,
            'token': token,
            'relauncher_pid': proc.pid,
            'waiter_script': str(waiter_path),
        }

    shell = f"""
set -eu
log={json.dumps(str(relaunch_log))}
stamp={json.dumps(stamp_path)}
token={json.dumps(token)}
pid={int(pid)}
port={int(port)}
log_line() {{ echo "$(date -Iseconds 2>/dev/null || date) [$token] $1" >>"$log" 2>/dev/null || true; }}
clear_stamp() {{
  if [ -f "$stamp" ]; then
    if ! grep -q "$token" "$stamp" 2>/dev/null; then
      return 0
    fi
    rm -f "$stamp" 2>/dev/null || true
  fi
}}
log_line "relauncher started; waiting for pid=$pid port=$port (max {wait_budget}s)"
deadline=$(( $(date +%s) + {wait_budget} ))
released=0
while kill -0 "$pid" 2>/dev/null; do
  now=$(date +%s)
  if [ "$now" -ge "$deadline" ]; then
    log_line "timed out waiting for pid=$pid; aborting relaunch"
    clear_stamp
    exit 2
  fi
  sleep 0.25
done
released=1
log_line "pid=$pid exited; settle then start"
sleep {max(0.2, float(delay_seconds or 0.8))}
if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 1 "http://127.0.0.1:$port/" >/dev/null 2>&1; then
    log_line "port $port already healthy after exit; skip start"
    clear_stamp
    exit 0
  fi
fi
cd {json.dumps(root)}
log_line "starting dashboard via {script.name}"
if [ -f {json.dumps(str(script))} ]; then
  nohup {json.dumps(str(script))} >/dev/null 2>&1 &
fi
clear_stamp
exit 0
"""
    cmd = ['/bin/bash', '-lc', shell]
    try:
        subprocess.Popen(
            cmd,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except Exception as exc:
        return {
            'ok': False,
            'message': f'Failed to schedule dashboard relaunch: {exc}',
        }
    return {
        'ok': True,
        'message': 'Dashboard panel is restarting.',
        'relaunch_log': str(relaunch_log),
        'port': port,
        'pid': pid,
        'token': token,
    }


def restart_dashboard_panel(delay_seconds: float = 0.5):
    """Schedule a one-shot detached relaunch, then exit this process once.

    Multi-layer guards against hang / restart storms:
    1. process-local single-flight (no double exit / double relauncher)
    2. on-disk cooldown stamp (cross-request debounce)
    3. relauncher hard deadline + no force-start while old PID is alive
    4. skip start if port already healthy after exit
    """
    global _DASHBOARD_EXIT_SCHEDULED, _DASHBOARD_RESTART_SCHEDULED

    with _DASHBOARD_LIFECYCLE_LOCK:
        if _DASHBOARD_RESTART_SCHEDULED or _DASHBOARD_EXIT_SCHEDULED:
            return {
                'ok': False,
                'message': 'Dashboard restart/stop already scheduled in this process.',
            }
        blocked = _dashboard_restart_in_cooldown()
        if blocked:
            return blocked

        token = f'{os.getpid()}-{time.time_ns()}'
        settle = max(0.4, float(delay_seconds or 0.5))
        scheduled = _spawn_dashboard_relauncher(delay_seconds=settle, token=token)
        if not scheduled.get('ok'):
            return scheduled

        _write_dashboard_restart_stamp({
            'token': token,
            'pid': os.getpid(),
            'port': scheduled.get('port') or get_dashboard_port(),
            'scheduled_at': time.time(),
            'relaunch_log': scheduled.get('relaunch_log'),
        })
        _DASHBOARD_RESTART_SCHEDULED = True
        _DASHBOARD_EXIT_SCHEDULED = True

        def _exit_later():
            # Give the HTTP response a moment to flush, then hard-exit once.
            time.sleep(max(0.15, min(settle, 2.0)))
            os._exit(0)

        threading.Thread(target=_exit_later, name='dashboard-restart-exit', daemon=True).start()
        return scheduled



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
    if action == 'restart':
        return """
$ErrorActionPreference = 'Stop'
Stop-Service iphlpsvc -Force
Start-Sleep -Seconds 1
Set-Service iphlpsvc -StartupType Manual
Start-Service iphlpsvc
"""
    raise ValueError('Invalid IP Helper action.')


def set_ip_helper_service(action, elevated: bool = True):
    action = str(action or '').strip().lower()
    if action not in ('start', 'stop', 'restart'):
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
            'message': {
                'start': 'IP Helper service is running.',
                'stop': 'IP Helper service is stopped.',
                'restart': 'IP Helper service was restarted.',
            }[action],
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


def _oauth_manager_port() -> int:
    for path in (OAUTH_MANAGER_PORT_FILE, OAUTH_MANAGER_LEGACY_PORT_FILE):
        try:
            port = int(path.read_text(encoding='utf-8', errors='ignore').strip())
            if 1 <= port <= 65535:
                return port
        except Exception:
            continue
    return OAUTH_MANAGER_DEFAULT_PORT


def _pid_is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        return psutil.Process(int(pid)).is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, TypeError, ValueError):
        try:
            os.kill(int(pid), 0)
            return True
        except Exception:
            return False


def _read_oauth_manager_pid_file() -> int | None:
    try:
        pid = int(OAUTH_MANAGER_PID_FILE.read_text(encoding='utf-8', errors='ignore').strip())
    except Exception:
        return None
    return pid if _pid_is_alive(pid) else None


def _find_oauth_manager_pid_uncached():
    # Prefer the PID written by switcher.py itself.
    pid = _read_oauth_manager_pid_file()
    if pid:
        return pid

    # Then resolve by the dashboard listen port.
    port = _oauth_manager_port()
    listener_pid = find_proxy_listener_pid(port)
    if listener_pid:
        name = (get_process_name(listener_pid) or '').lower()
        if name in ('python.exe', 'pythonw.exe', 'python', 'pythonw', 'py.exe', 'pyw.exe'):
            return listener_pid

    # Fallback: scan process command lines for switcher.py --dashboard.
    # Real launches often use a relative path from OAUTH_MANAGER_DIR, so do not
    # require the absolute directory needle that previously caused permanent red status.
    try:
        needle = 'switcher.py'
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline') or []
                text = ' '.join(str(part) for part in cmdline).lower()
                name = str(proc.info.get('name') or '').lower()
                if 'switcher.py' not in text or '--dashboard' not in text:
                    continue
                if 'powershell' in name or 'cmd.exe' in name:
                    continue
                if needle in text:
                    return int(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, TypeError, ValueError, KeyError):
                continue
    except Exception:
        pass
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


def _openclaw_launch_details(command=None):
    return {
        'command': command or _openclaw_command(),
        'cwd': str(OPENCLAW_HOME if OPENCLAW_HOME.exists() else PROXY_ROOT),
        'stdout': str(OPENCLAW_STDOUT),
        'stderr': str(OPENCLAW_STDERR),
    }


def start_openclaw_gateway():
    _openclaw_pid_cache['time'] = 0
    with process_lock:
        proc = processes.get('openclaw')
        running_pid = proc.pid if process_alive(proc) else find_openclaw_gateway_pid()
        if running_pid:
            return {'ok': True, 'message': 'OpenClaw gateway is already running.', 'pid': running_pid, **_openclaw_launch_details()}

        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            fout = open(OPENCLAW_STDOUT, 'w', encoding='utf-8', errors='ignore')
            ferr = open(OPENCLAW_STDERR, 'w', encoding='utf-8', errors='ignore')
            command = _openclaw_command()
            proc = subprocess.Popen(
                command,
                cwd=str(OPENCLAW_HOME if OPENCLAW_HOME.exists() else PROXY_ROOT),
                stdout=fout,
                stderr=ferr,
                stdin=subprocess.DEVNULL,
                creationflags=_creationflags(),
            )
            processes['openclaw'] = proc
            _openclaw_pid_cache['value'] = proc.pid
            _openclaw_pid_cache['time'] = time.time()
            return {
                'ok': True,
                'message': 'Started OpenClaw gateway. It may take a minute or two to become ready.',
                'pid': proc.pid,
                **_openclaw_launch_details(command),
            }
        except Exception as exc:
            return {'ok': False, 'message': f'Failed to start OpenClaw gateway: {exc}', **_openclaw_launch_details()}


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
    return f'http://127.0.0.1:{_oauth_manager_port()}'


def _oauth_manager_python_candidates() -> list[str]:
    candidates = []
    for name in ('pythonw', 'python', 'pyw', 'py'):
        path = shutil.which(name)
        if path and path not in candidates:
            candidates.append(path)
    return candidates


def _oauth_manager_launch_command() -> list[str]:
    switcher = str(OAUTH_MANAGER_SWITCHER)
    for python_bin in _oauth_manager_python_candidates():
        lower = python_bin.lower()
        if lower.endswith('py.exe') or lower.endswith('pyw.exe') or Path(python_bin).name.lower() in ('py', 'pyw'):
            return [python_bin, '-3.12', switcher, '--dashboard']
        return [python_bin, switcher, '--dashboard']
    return ['python', switcher, '--dashboard']


def start_oauth_manager():
    _oauth_manager_pid_cache['time'] = 0
    if not OAUTH_MANAGER_DIR.exists():
        return {'ok': False, 'message': f'OAuth Manager directory was not found: {OAUTH_MANAGER_DIR}'}
    if not OAUTH_MANAGER_SWITCHER.exists():
        return {'ok': False, 'message': f'switcher.py was not found: {OAUTH_MANAGER_SWITCHER}'}

    command = None
    proc = None
    with process_lock:
        running_pid = None
        tracked = processes.get('oauth_manager')
        if process_alive(tracked):
            running_pid = tracked.pid
        if not running_pid:
            running_pid = find_oauth_manager_pid()
        if running_pid:
            _oauth_manager_pid_cache['value'] = running_pid
            _oauth_manager_pid_cache['time'] = time.time()
            return {
                'ok': True,
                'message': f'OAuth Manager is already running at {_oauth_manager_url()}.',
                'pid': running_pid,
                'url': _oauth_manager_url(),
            }

        try:
            OAUTH_MANAGER_RUN_DIR.mkdir(parents=True, exist_ok=True)
            OAUTH_MANAGER_STDOUT.parent.mkdir(parents=True, exist_ok=True)
            command = _oauth_manager_launch_command()
            env = os.environ.copy()
            env['OAUTH_MANAGER_NO_BROWSER'] = '1'
            fout = open(OAUTH_MANAGER_STDOUT, 'w', encoding='utf-8', errors='ignore')
            ferr = open(OAUTH_MANAGER_STDERR, 'w', encoding='utf-8', errors='ignore')
            creationflags = 0
            if is_windows():
                creationflags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            proc = subprocess.Popen(
                command,
                cwd=str(OAUTH_MANAGER_DIR),
                stdout=fout,
                stderr=ferr,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
                close_fds=False if is_windows() else True,
            )
            processes['oauth_manager'] = proc
        except Exception as exc:
            processes['oauth_manager'] = None
            return {'ok': False, 'message': f'Failed to start OAuth Manager: {exc}', 'url': _oauth_manager_url()}

    # switcher.py rewrites run/dashboard.pid; wait for TCP listen readiness outside process_lock.
    deadline = time.time() + 12.0
    while time.time() < deadline:
        if not process_alive(proc) and not _read_oauth_manager_pid_file():
            break
        _oauth_manager_pid_cache['time'] = 0
        listener_pid = find_proxy_listener_pid(_oauth_manager_port())
        ready_pid = find_oauth_manager_pid() or (proc.pid if process_alive(proc) else None)
        if ready_pid and listener_pid:
            break
        time.sleep(0.25)

    listener_pid = find_proxy_listener_pid(_oauth_manager_port())
    if not listener_pid and not process_alive(proc) and not find_oauth_manager_pid():
        err_tail = ''
        try:
            err_tail = OAUTH_MANAGER_STDERR.read_text(encoding='utf-8', errors='ignore')[-500:]
        except Exception:
            pass
        with process_lock:
            processes['oauth_manager'] = None
        message = 'Failed to start OAuth Manager.'
        if err_tail.strip():
            message = f'{message} {err_tail.strip()}'
        return {'ok': False, 'message': message, 'command': command, 'url': _oauth_manager_url()}

    ready_pid = listener_pid or find_oauth_manager_pid() or proc.pid
    _oauth_manager_pid_cache['value'] = ready_pid
    _oauth_manager_pid_cache['time'] = time.time()
    return {
        'ok': True,
        'message': f'Started OAuth Manager at {_oauth_manager_url()}.',
        'pid': ready_pid,
        'command': command,
        'url': _oauth_manager_url(),
    }


def stop_oauth_manager():
    _oauth_manager_pid_cache['time'] = 0
    stopped = False
    with process_lock:
        proc = processes.get('oauth_manager')
        if process_alive(proc):
            stopped = _kill_pid_tree(proc.pid) or kill_process(proc) or stopped
            processes['oauth_manager'] = None

    pid = find_oauth_manager_pid()
    if pid:
        stopped = _kill_pid_tree(pid) or stopped

    stop_script = OAUTH_MANAGER_DIR / 'scripts' / 'stop_dashboard.py'
    stop_bat = OAUTH_MANAGER_DIR / 'stop.bat'
    try:
        if stop_script.exists():
            subprocess.run(
                [shutil.which('python') or 'python', str(stop_script)],
                cwd=str(OAUTH_MANAGER_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_creationflags(),
                timeout=15,
            )
            stopped = True
        elif stop_bat.exists():
            subprocess.run(
                ['cmd', '/c', str(stop_bat)],
                cwd=str(OAUTH_MANAGER_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_creationflags(),
                timeout=15,
            )
            stopped = True
    except Exception:
        pass

    try:
        if OAUTH_MANAGER_PID_FILE.exists():
            OAUTH_MANAGER_PID_FILE.unlink()
    except Exception:
        pass

    _oauth_manager_pid_cache['value'] = None
    _oauth_manager_pid_cache['time'] = time.time()
    return {
        'ok': True,
        'message': 'Stopped OAuth Manager.' if stopped else 'OAuth Manager was not running.',
        'url': _oauth_manager_url(),
    }


def restart_oauth_manager():
    stop_oauth_manager()
    time.sleep(0.4)
    return start_oauth_manager()


def create_grok_port() -> int:
    raw = str(os.environ.get('GROK_UI_PORT') or '').strip()
    try:
        port = int(raw) if raw else CREATE_GROK_DEFAULT_PORT
    except Exception:
        port = CREATE_GROK_DEFAULT_PORT
    return port if port > 0 else CREATE_GROK_DEFAULT_PORT


def _create_grok_url() -> str:
    return f'http://127.0.0.1:{create_grok_port()}/'


def _create_grok_health_ok() -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(f'{_create_grok_url().rstrip("/")}/api/health', timeout=1.2) as resp:
            if getattr(resp, 'status', 200) >= 400:
                return False
            body = resp.read(200).decode('utf-8', errors='ignore')
            return '"ok"' in body or 'true' in body.lower()
    except Exception:
        return False


def find_create_grok_pid():
    tracked = processes.get('create_grok')
    if process_alive(tracked):
        return tracked.pid
    return find_proxy_listener_pid(create_grok_port())


def _create_grok_node_bin() -> str | None:
    # Shared by Node-based side services (e.g. 77chat); keep name for callers.
    candidates = []
    which_node = shutil.which('node')
    if which_node:
        candidates.append(which_node)
    candidates.extend([
        str(Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'nodejs' / 'node.exe'),
        str(Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'nodejs' / 'node.exe'),
        str(Path.home() / 'AppData' / 'Roaming' / 'nvm' / 'current' / 'node.exe'),
    ])
    seen = set()
    for path in candidates:
        key = str(path or '').strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        if Path(path).exists():
            return str(path)
    return which_node


def _create_grok_python_bin() -> str | None:
    """Prefer project venv, then PATH python/py."""
    candidates = [
        CREATE_GROK_DIR / '.venv' / 'Scripts' / 'python.exe',
        CREATE_GROK_DIR / '.venv' / 'bin' / 'python',
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    for name in ('python', 'python3', 'py'):
        found = shutil.which(name)
        if found:
            return found
    # Common Windows install locations as last resort.
    for path in (
        Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Python' / 'Python313' / 'python.exe',
        Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Python' / 'Python312' / 'python.exe',
        Path(r'C:\Python313\python.exe'),
        Path(r'C:\Python312\python.exe'),
    ):
        if path and path.exists():
            return str(path)
    return None


def start_create_grok():
    if not CREATE_GROK_DIR.exists():
        return {'ok': False, 'message': f'grok-register-mint 目录不存在: {CREATE_GROK_DIR}', 'url': _create_grok_url()}
    if not CREATE_GROK_ENTRY.exists():
        return {'ok': False, 'message': f'web_ui.py 不存在: {CREATE_GROK_ENTRY}', 'url': _create_grok_url()}

    port = create_grok_port()
    # Resolve binary + listener outside process_lock so a stuck peer start
    # cannot freeze this button behind slow PATH / netstat work.
    with process_lock:
        tracked = processes.get('create_grok')
        running_pid = tracked.pid if process_alive(tracked) else None
    if not running_pid:
        running_pid = find_proxy_listener_pid(port)
    if running_pid:
        return {
            'ok': True,
            'message': f'grok-register-mint 已在运行：{_create_grok_url()}',
            'pid': running_pid,
            'url': _create_grok_url(),
        }

    python_bin = _create_grok_python_bin()
    if not python_bin:
        return {
            'ok': False,
            'message': '未找到 Python。请在 grok-register-mint 下创建 .venv，或把 python 加入 PATH。',
            'url': _create_grok_url(),
        }

    command = [python_bin, str(CREATE_GROK_ENTRY), '--host', '127.0.0.1', '--port', str(port)]
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    env['GROK_UI_HOST'] = env.get('GROK_UI_HOST') or '127.0.0.1'
    env['GROK_UI_PORT'] = str(port)
    proc = None
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        fout = open(CREATE_GROK_STDOUT, 'w', encoding='utf-8', errors='ignore')
        ferr = open(CREATE_GROK_STDERR, 'w', encoding='utf-8', errors='ignore')
        creationflags = 0
        if is_windows():
            creationflags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        with process_lock:
            # Re-check under lock to avoid double-start races.
            tracked = processes.get('create_grok')
            if process_alive(tracked):
                return {
                    'ok': True,
                    'message': f'grok-register-mint 已在运行：{_create_grok_url()}',
                    'pid': tracked.pid,
                    'url': _create_grok_url(),
                }
            existing = find_proxy_listener_pid(port)
            if existing:
                return {
                    'ok': True,
                    'message': f'grok-register-mint 已在运行：{_create_grok_url()}',
                    'pid': existing,
                    'url': _create_grok_url(),
                }
            proc = subprocess.Popen(
                command,
                cwd=str(CREATE_GROK_DIR),
                stdout=fout,
                stderr=ferr,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
                close_fds=False if is_windows() else True,
            )
            processes['create_grok'] = proc
    except Exception as exc:
        with process_lock:
            processes['create_grok'] = None
        return {'ok': False, 'message': f'启动 grok-register-mint 失败: {exc}', 'url': _create_grok_url()}

    ready = wait_for_listener(port, proc=proc, timeout_seconds=15.0)
    if not ready and not process_alive(proc):
        err_tail = ''
        try:
            err_tail = CREATE_GROK_STDERR.read_text(encoding='utf-8', errors='ignore')[-500:]
        except Exception:
            pass
        with process_lock:
            processes['create_grok'] = None
        message = 'grok-register-mint 启动失败。'
        if err_tail.strip():
            message = f'{message} {err_tail.strip()}'
        return {'ok': False, 'message': message, 'command': command, 'url': _create_grok_url()}

    ready_pid = find_proxy_listener_pid(port) or (proc.pid if process_alive(proc) else None)
    return {
        'ok': True,
        'message': f'已启动 grok-register-mint：{_create_grok_url()}',
        'pid': ready_pid,
        'command': command,
        'url': _create_grok_url(),
    }


def stop_create_grok():
    stopped = False
    with process_lock:
        proc = processes.get('create_grok')
        if process_alive(proc):
            stopped = _kill_pid_tree(proc.pid) or kill_process(proc) or stopped
            processes['create_grok'] = None

    pid = find_proxy_listener_pid(create_grok_port())
    if pid:
        stopped = _kill_pid_tree(pid) or stopped

    return {
        'ok': True,
        'message': '已停止 grok-register-mint。' if stopped else 'grok-register-mint 未在运行。',
        'url': _create_grok_url(),
    }


def restart_create_grok():
    stop_create_grok()
    time.sleep(0.4)
    return start_create_grok()


def chat77_port() -> int:
    return CHAT77_DEFAULT_PORT


def _chat77_url() -> str:
    return f'http://127.0.0.1:{chat77_port()}/'


def find_chat77_pid():
    tracked = processes.get('chat77')
    if process_alive(tracked):
        return tracked.pid
    return find_proxy_listener_pid(chat77_port())


def start_chat77():
    if not CHAT77_DIR.exists():
        return {'ok': False, 'message': f'77chat 目录不存在: {CHAT77_DIR}', 'url': _chat77_url()}
    if not CHAT77_SERVER.exists():
        return {'ok': False, 'message': f'src/server/index.js 不存在: {CHAT77_SERVER}', 'url': _chat77_url()}

    port = chat77_port()
    # Keep process_lock short: node lookup + netstat must not sit under the lock,
    # otherwise a deadlocked peer service start freezes this button forever.
    with process_lock:
        tracked = processes.get('chat77')
        running_pid = tracked.pid if process_alive(tracked) else None
    if not running_pid:
        running_pid = find_proxy_listener_pid(port)
    if running_pid:
        return {
            'ok': True,
            'message': f'77chat 已在运行：{_chat77_url()}',
            'pid': running_pid,
            'url': _chat77_url(),
        }

    node_bin = _create_grok_node_bin()
    if not node_bin:
        return {'ok': False, 'message': '未找到 node，请先安装 Node.js 并加入 PATH。', 'url': _chat77_url()}

    command = [node_bin, str(CHAT77_SERVER)]
    env = os.environ.copy()
    env['PORT'] = str(port)
    proc = None
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        fout = open(CHAT77_STDOUT, 'w', encoding='utf-8', errors='ignore')
        ferr = open(CHAT77_STDERR, 'w', encoding='utf-8', errors='ignore')
        creationflags = 0
        if is_windows():
            creationflags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        with process_lock:
            tracked = processes.get('chat77')
            if process_alive(tracked):
                return {
                    'ok': True,
                    'message': f'77chat 已在运行：{_chat77_url()}',
                    'pid': tracked.pid,
                    'url': _chat77_url(),
                }
            existing = find_proxy_listener_pid(port)
            if existing:
                return {
                    'ok': True,
                    'message': f'77chat 已在运行：{_chat77_url()}',
                    'pid': existing,
                    'url': _chat77_url(),
                }
            proc = subprocess.Popen(
                command,
                cwd=str(CHAT77_DIR),
                stdout=fout,
                stderr=ferr,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
                close_fds=False if is_windows() else True,
            )
            processes['chat77'] = proc
    except Exception as exc:
        with process_lock:
            processes['chat77'] = None
        return {'ok': False, 'message': f'启动 77chat 失败: {exc}', 'url': _chat77_url()}

    ready = wait_for_listener(port, proc=proc, timeout_seconds=12.0)
    if not ready and not process_alive(proc):
        err_tail = ''
        try:
            err_tail = CHAT77_STDERR.read_text(encoding='utf-8', errors='ignore')[-500:]
        except Exception:
            pass
        with process_lock:
            processes['chat77'] = None
        message = '77chat 启动失败。'
        if err_tail.strip():
            message = f'{message} {err_tail.strip()}'
        return {'ok': False, 'message': message, 'command': command, 'url': _chat77_url()}

    ready_pid = find_proxy_listener_pid(port) or (proc.pid if process_alive(proc) else None)
    return {
        'ok': True,
        'message': f'已启动 77chat：{_chat77_url()}',
        'pid': ready_pid,
        'command': command,
        'url': _chat77_url(),
    }


def stop_chat77():
    stopped = False
    with process_lock:
        proc = processes.get('chat77')
        if process_alive(proc):
            stopped = _kill_pid_tree(proc.pid) or kill_process(proc) or stopped
            processes['chat77'] = None

    pid = find_proxy_listener_pid(chat77_port())
    if pid:
        stopped = _kill_pid_tree(pid) or stopped

    return {
        'ok': True,
        'message': '已停止 77chat。' if stopped else '77chat 未在运行。',
        'url': _chat77_url(),
    }


def restart_chat77():
    stop_chat77()
    time.sleep(0.4)
    return start_chat77()


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



def _managed_listener_info(port: int):
    """Return listener info for a port: None if free, or {pid, name, managed}."""
    pid = find_proxy_listener_pid(port)
    if not pid:
        return None
    name = str(get_process_name(pid) or '').strip().lower()
    return {
        'pid': pid,
        'name': name,
        'managed': name in _managed_proxy_process_names(),
    }


def _persist_proxy_applied_state(state, auth_files, bind_host, access_api_key):
    """Mirror applied/selected auth + bind metadata after a successful start or adopt."""
    selected_items = auth_files or []
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
    return selected_items


def _finalize_proxy_start_result(selected_items, media_result=None, *, adopted=False, core_pid=None, gateway_pid=None):
    if media_result is None:
        media_result = start_media_proxy()
    media_message = ''
    if media_result.get('ok'):
        media_message = ' MediaProxy is ready on port 8320.'
    else:
        media_message = f' MediaProxy was not started: {media_result.get("message", "unknown error")}'
    if adopted:
        message = (
            f'RelayX already running (core PID {core_pid}, gateway PID {gateway_pid}); '
            f'adopted existing instance with {len(selected_items)} active account file(s).{media_message}'
        )
    else:
        message = f'Started RelayX with storage/auth account files: {len(selected_items)} active.{media_message}'
    return {
        'ok': True,
        'message': message,
        'adopted': bool(adopted),
        'media_proxy': media_result,
        'core_pid': core_pid,
        'gateway_pid': gateway_pid,
    }


def start_proxy(*, _from_restart=False):
    if not _cli_binary_ready():
        return {'ok': False, 'message': _cli_unavailable_message()}
    if not ACCESS_GATEWAY_BINARY.is_file():
        return {'ok': False, 'message': f'Access gateway binary was not found: {ACCESS_GATEWAY_BINARY}. Run CLIProxyAPI-AccessGateway/build.ps1 first.'}
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

    core_port = core_proxy_port()
    proc = None
    gateway_proc = None
    reclaimed = False
    # process_lock is a non-reentrant Lock. Never call start_media_proxy /
    # _finalize_proxy_start_result / build_runtime_config while holding it —
    # those paths re-enter the same lock (or run multi-second egress probes)
    # and freeze the homepage Start button.
    adopt_info = None
    reclaim_pids = []

    with process_lock:
        if not _from_restart and (_proxy_start_state.get('starting') or _proxy_start_state.get('restarting')):
            return {'ok': False, 'message': 'RelayX start is already in progress. Please wait a moment and retry.'}
        if process_alive(processes.get('proxy')) and process_alive(processes.get('access_gateway')):
            return {'ok': True, 'message': 'RelayX is already running.', 'adopted': False}

        gateway_info = _managed_listener_info(8317)
        core_info = _managed_listener_info(core_port)
        for port, info in ((8317, gateway_info), (core_port, core_info)):
            if info and not info.get('managed'):
                label = info.get('name') or f'PID {info.get("pid")}'
                return {'ok': False, 'message': f'Port {port} is occupied by {label}. Please stop it first.'}

        if (
            gateway_info
            and gateway_info.get('managed')
            and core_info
            and core_info.get('managed')
        ):
            adopt_info = {
                'core_pid': core_info.get('pid'),
                'gateway_pid': gateway_info.get('pid'),
            }
        else:
            for port in (8317, core_port):
                info = gateway_info if port == 8317 else core_info
                if info is None:
                    info = _managed_listener_info(port)
                if not info:
                    continue
                if not info.get('managed'):
                    label = info.get('name') or f'PID {info.get("pid")}'
                    return {'ok': False, 'message': f'Port {port} is occupied by {label}. Please stop it first.'}
                reclaim_pids.append((port, info['pid']))
            # Claim the start slot under lock; heavy work runs after release.
            _proxy_start_state['starting'] = True
            _proxy_start_state['started_at'] = time.time()

    if adopt_info is not None:
        selected_items = _persist_proxy_applied_state(state, auth_files, bind_host, access_api_key)
        return _finalize_proxy_start_result(
            selected_items,
            adopted=True,
            core_pid=adopt_info.get('core_pid'),
            gateway_pid=adopt_info.get('gateway_pid'),
        )

    try:
        for port, pid in reclaim_pids:
            if not stop_pid(pid):
                return {'ok': False, 'message': f'Port {port} is occupied by existing RelayX (PID {pid}) and could not be stopped.'}
            reclaimed = True

        try:
            # Egress probing / provider config rebuild can take seconds — keep
            # it outside process_lock so /api/status and other buttons stay live.
            build_runtime_config(
                bind_host='127.0.0.1',
                listen_port=core_port,
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

        with process_lock:
            stdout = open(PROXY_STDOUT, 'a', encoding='utf-8', errors='ignore')
            stderr = open(PROXY_STDERR, 'a', encoding='utf-8', errors='ignore')
            proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, creationflags=_creationflags(), env=merged_env)
            processes['proxy'] = proc

        if reclaimed:
            time.sleep(0.3)

        if not wait_for_listener(core_port, proc=proc, timeout_seconds=120.0):
            with process_lock:
                kill_process(proc)
                processes['proxy'] = None
            return {'ok': False, 'message': f'CPA core did not become ready on 127.0.0.1:{core_port} within 120s. Check {PROXY_STDERR}.'}

        with process_lock:
            ACCESS_GATEWAY_STDOUT.parent.mkdir(parents=True, exist_ok=True)
            gateway_stdout = open(ACCESS_GATEWAY_STDOUT, 'a', encoding='utf-8', errors='ignore')
            gateway_stderr = open(ACCESS_GATEWAY_STDERR, 'a', encoding='utf-8', errors='ignore')
            gateway_cmd = [str(ACCESS_GATEWAY_BINARY), '-listen', f'{bind_host}:8317', '-upstream', f'http://127.0.0.1:{core_port}', '-config', str(RUNTIME_CONFIG)]
            gateway_proc = subprocess.Popen(gateway_cmd, cwd=str(ACCESS_GATEWAY_ROOT), stdout=gateway_stdout, stderr=gateway_stderr, stdin=subprocess.DEVNULL, creationflags=_creationflags())
            processes['access_gateway'] = gateway_proc

        if not wait_for_listener(8317, proc=gateway_proc):
            with process_lock:
                kill_process(gateway_proc)
                kill_process(proc)
                processes['access_gateway'] = None
                processes['proxy'] = None
            return {'ok': False, 'message': f'Access gateway did not become ready on {bind_host}:8317. Check {ACCESS_GATEWAY_STDERR}.'}

        core_pid = proc.pid
        gateway_pid = gateway_proc.pid
    finally:
        _set_proxy_starting(False)

    selected_items = _persist_proxy_applied_state(state, auth_files, bind_host, access_api_key)
    return _finalize_proxy_start_result(
        selected_items,
        adopted=False,
        core_pid=core_pid,
        gateway_pid=gateway_pid,
    )



def stop_proxy():
    with process_lock:
        gateway_stopped = kill_process(processes.get('access_gateway'))
        processes['access_gateway'] = None
        proc = processes.get('proxy')
        stopped = kill_process(proc)
        processes['proxy'] = None
    for port in (8317, core_proxy_port()):
        listener_pid = find_proxy_listener_pid(port)
        if listener_pid:
            process_name = str(get_process_name(listener_pid) or '').strip().lower()
            if process_name in _managed_proxy_process_names():
                stopped = stop_pid(listener_pid) or stopped
    state = load_state()
    state['applied_auth'] = None
    state['applied_auth_ref'] = None
    state['applied_auths'] = []
    state['applied_auth_refs'] = []
    state['last_proxy_bind_host'] = None
    state['last_proxy_api_key'] = None
    save_state(state)
    return {'ok': True, 'message': 'Stopped RelayX.' if (stopped or gateway_stopped) else 'RelayX was not running.'}


def restart_proxy():
    with process_lock:
        if _proxy_start_state.get('starting') or _proxy_start_state.get('restarting'):
            return {'ok': False, 'message': 'RelayX restart is already in progress. Please wait a moment and retry.'}
        _proxy_start_state['restarting'] = True
    try:
        stop_proxy()
        time.sleep(0.3)
        return start_proxy(_from_restart=True)
    finally:
        _set_proxy_restarting(False)


def media_proxy_config_path():
    preferred = MEDIA_PROXY_ROOT / 'config.json'
    if preferred.exists():
        return preferred
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
    time.sleep(0.3)
    return start_media_proxy()


def grok2api_config_path() -> Path:
    return GROK2API_ROOT / 'config.yaml'


def grok2api_binary_path() -> Path:
    name = 'grok2api.exe' if is_windows() else 'grok2api'
    return GROK2API_ROOT / name


def wait_for_grok2api_ready(timeout_seconds: float = 45.0):
    backend_ready = wait_for_listener(grok2api_port(), timeout_seconds=timeout_seconds)
    return backend_ready and wait_for_listener(grok2api_frontend_port(), timeout_seconds=timeout_seconds)


def _start_grok2api_process(command, cwd: Path, stdout_path: Path, stderr_path: Path, env=None):
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout = open(stdout_path, 'a', encoding='utf-8', errors='ignore')
    stderr = open(stderr_path, 'a', encoding='utf-8', errors='ignore')
    try:
        return subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=_creationflags(),
        )
    finally:
        stdout.close()
        stderr.close()


def start_grok2api_backend():
    if not GROK2API_ROOT.exists():
        return {'ok': False, 'message': f'Grok2API directory was not found: {GROK2API_ROOT}'}
    config_path = grok2api_config_path()
    if not config_path.exists():
        return {'ok': False, 'message': f'Grok2API config was not found: {config_path}'}
    if find_proxy_listener_pid(grok2api_port()):
        return {'ok': True, 'message': f'Grok2API backend is already running on port {grok2api_port()}.'}

    binary = grok2api_binary_path()
    if binary.exists():
        command = [str(binary), '--config', str(config_path)]
        backend_cwd = GROK2API_ROOT
    elif command_exists('go'):
        command = ['go', 'run', './cmd/grok2api', '--config', str(config_path)]
        backend_cwd = GROK2API_ROOT / 'backend'
    else:
        return {
            'ok': False,
            'message': f'Grok2API binary was not found at {binary}, and Go runtime is unavailable.',
        }

    with process_lock:
        try:
            processes['grok2api'] = _start_grok2api_process(
                command, backend_cwd, GROK2API_STDOUT, GROK2API_STDERR
            )
            proc = processes['grok2api']
        except OSError as exc:
            return {'ok': False, 'message': f'Failed to start Grok2API backend: {exc}'}
    if wait_for_listener(grok2api_port(), proc=proc, timeout_seconds=45.0):
        return {'ok': True, 'message': f'Started Grok2API backend on port {grok2api_port()}.'}
    kill_process(proc)
    processes['grok2api'] = None
    return {'ok': False, 'message': f'Grok2API backend did not become ready on port {grok2api_port()}.'}


def start_grok2api_frontend():
    frontend_root = GROK2API_ROOT / 'frontend'
    if not (frontend_root / 'package.json').exists():
        return {'ok': False, 'message': f'Grok2API frontend was not found: {frontend_root}'}
    if find_proxy_listener_pid(grok2api_frontend_port()):
        return {'ok': True, 'message': f'Grok2API frontend is already running on port {grok2api_frontend_port()}.'}
    pnpm = shutil.which('pnpm.cmd' if is_windows() else 'pnpm') or shutil.which('pnpm')
    if not pnpm:
        return {'ok': False, 'message': 'pnpm was not found in PATH. Install pnpm before starting the Grok2API frontend.'}

    frontend_command = [pnpm, 'exec', 'vite', '--host', '127.0.0.1', '--port', str(grok2api_frontend_port()), '--strictPort']
    if is_windows():
        frontend_command = [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/s', '/c', subprocess.list2cmdline(frontend_command)]
    frontend_env = os.environ.copy()
    frontend_env['VITE_DEV_API_TARGET'] = f'http://127.0.0.1:{grok2api_port()}'
    with process_lock:
        try:
            processes['grok2api_frontend'] = _start_grok2api_process(
                frontend_command,
                frontend_root,
                GROK2API_FRONTEND_STDOUT,
                GROK2API_FRONTEND_STDERR,
                env=frontend_env,
            )
            proc = processes['grok2api_frontend']
        except OSError as exc:
            return {'ok': False, 'message': f'Failed to start Grok2API frontend: {exc}'}
    if wait_for_listener(grok2api_frontend_port(), proc=proc, timeout_seconds=45.0):
        return {
            'ok': True,
            'message': f'Started Grok2API frontend on port {grok2api_frontend_port()}.',
            'url': f'http://127.0.0.1:{grok2api_frontend_port()}/',
        }
    kill_process(proc)
    processes['grok2api_frontend'] = None
    return {'ok': False, 'message': f'Grok2API frontend did not become ready on port {grok2api_frontend_port()}.'}


def stop_grok2api_backend():
    with process_lock:
        stopped = kill_process(processes.get('grok2api'))
        processes['grok2api'] = None
    listener_pid = find_proxy_listener_pid(grok2api_port())
    if listener_pid:
        stopped = stop_pid(listener_pid) or stopped
    return {
        'ok': True,
        'message': 'Stopped Grok2API backend.' if stopped else 'Grok2API backend was not running.',
    }


def stop_grok2api_frontend():
    with process_lock:
        stopped = kill_process(processes.get('grok2api_frontend'))
        processes['grok2api_frontend'] = None
    listener_pid = find_proxy_listener_pid(grok2api_frontend_port())
    if listener_pid:
        stopped = stop_pid(listener_pid) or stopped
    return {
        'ok': True,
        'message': 'Stopped Grok2API frontend.' if stopped else 'Grok2API frontend was not running.',
    }


def restart_grok2api_backend():
    stop_grok2api_backend()
    time.sleep(0.3)
    return start_grok2api_backend()


def restart_grok2api_frontend():
    stop_grok2api_frontend()
    time.sleep(0.3)
    return start_grok2api_frontend()


def start_grok2api():
    backend = start_grok2api_backend()
    if not backend.get('ok'):
        return backend
    frontend = start_grok2api_frontend()
    if not frontend.get('ok'):
        return frontend
    return {
        'ok': True,
        'message': f'Started Grok2API frontend ({grok2api_frontend_port()}) and backend ({grok2api_port()}).',
        'url': f'http://127.0.0.1:{grok2api_frontend_port()}/',
    }


def stop_grok2api():
    frontend = stop_grok2api_frontend()
    backend = stop_grok2api_backend()
    return {
        'ok': True,
        'message': 'Stopped Grok2API frontend and backend.',
        'frontend': frontend,
        'backend': backend,
    }


def restart_grok2api():
    stop_grok2api()
    time.sleep(0.3)
    return start_grok2api()


def current_status(include_logs: bool = True):
    state = load_state()
    auth_files = list_auth_files()

    selected_items = auth_files
    applied_items = auth_files if process_alive(processes.get('proxy')) or find_proxy_listener_pid() else []
    selected_refs = [item.get('id') for item in selected_items if item.get('id')]
    applied_refs = [item.get('id') for item in applied_items if item.get('id')]

    selected_display = f'{len(selected_items)} active file(s)'
    applied_display = f'{len(applied_items)} active file(s)' if applied_items else None

    tracked_proxy_running = process_alive(processes.get('proxy')) and process_alive(processes.get('access_gateway'))
    tracked_media_proxy_running = process_alive(processes.get('media_proxy'))
    tracked_grok2api_running = process_alive(processes.get('grok2api'))
    tracked_grok2api_frontend_running = process_alive(processes.get('grok2api_frontend'))
    tracked_oauth_manager_running = process_alive(processes.get('oauth_manager'))
    tracked_openclaw_proc = processes.get('openclaw')
    tracked_openclaw_running = process_alive(tracked_openclaw_proc)
    tracked_create_grok_running = process_alive(processes.get('create_grok'))
    tracked_chat77_running = process_alive(processes.get('chat77'))
    oauth_manager_pid = find_oauth_manager_pid()
    oauth_manager_running = bool(tracked_oauth_manager_running or oauth_manager_pid)
    openclaw_pid = tracked_openclaw_proc.pid if tracked_openclaw_running else find_openclaw_gateway_pid()
    openclaw_running = bool(tracked_openclaw_running or openclaw_pid)
    create_grok_pid = processes.get('create_grok').pid if tracked_create_grok_running else find_proxy_listener_pid(create_grok_port())
    create_grok_running = bool(tracked_create_grok_running or create_grok_pid)
    chat77_pid = processes.get('chat77').pid if tracked_chat77_running else find_proxy_listener_pid(chat77_port())
    chat77_running = bool(tracked_chat77_running or chat77_pid)
    listener_pid = find_proxy_listener_pid()
    media_proxy_pid = processes.get('media_proxy').pid if tracked_media_proxy_running else find_proxy_listener_pid(media_proxy_port())
    grok2api_pid = processes.get('grok2api').pid if tracked_grok2api_running else find_proxy_listener_pid(grok2api_port())
    grok2api_frontend_pid = processes.get('grok2api_frontend').pid if tracked_grok2api_frontend_running else find_proxy_listener_pid(grok2api_frontend_port())
    listener_process_name = get_process_name(listener_pid) if listener_pid else None
    listener_is_proxy = bool(listener_pid and listener_process_name and listener_process_name.lower() in _managed_proxy_process_names())
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
        'grok2api_running': bool((tracked_grok2api_running or grok2api_pid) and (tracked_grok2api_frontend_running or grok2api_frontend_pid)),
        'grok2api_backend_running': bool(tracked_grok2api_running or grok2api_pid),
        'grok2api_frontend_running': bool(tracked_grok2api_frontend_running or grok2api_frontend_pid),
        'grok2api_pid': grok2api_pid,
        'grok2api_frontend_pid': grok2api_frontend_pid,
        'grok2api_url': f'http://127.0.0.1:{grok2api_frontend_port()}/',
        'grok2api_backend_url': f'http://127.0.0.1:{grok2api_port()}/',
        'grok2api_root': str(GROK2API_ROOT),
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
        'create_grok_running': create_grok_running,
        'create_grok_pid': create_grok_pid,
        'create_grok_url': _create_grok_url(),
        'create_grok_root': str(CREATE_GROK_DIR),
        'chat77_running': chat77_running,
        'chat77_pid': chat77_pid,
        'chat77_url': _chat77_url(),
        'chat77_root': str(CHAT77_DIR),
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
            'grok2api_stdout': read_tail(GROK2API_STDOUT),
            'grok2api_stderr': read_tail(GROK2API_STDERR),
            'grok2api_frontend_stdout': read_tail(GROK2API_FRONTEND_STDOUT),
            'grok2api_frontend_stderr': read_tail(GROK2API_FRONTEND_STDERR),
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


def restart_cloudflared_tunnel():
    stop_result = stop_cloudflared_tunnel()
    if not stop_result.get('ok'):
        return stop_result
    time.sleep(0.6)
    return start_cloudflared_tunnel()
