import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from backend.paths import PROJECT_ROOT

try:
    from winpty import PtyProcess
except Exception:
    PtyProcess = None


terminal_processes: dict[str, dict] = {}
terminal_lock = threading.Lock()
MAX_OUTPUT_CHARS = 160_000


def _creationflags():
    if os.name != 'nt':
        return 0
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def _terminal_cwd(value=None):
    raw = str(value or '').strip()
    if not raw:
        return str(PROJECT_ROOT)
    path = Path(raw)
    if path.exists() and path.is_dir():
        return str(path)
    return str(PROJECT_ROOT)


def _terminal_alive(proc):
    if not proc:
        return False
    if PtyProcess is not None and hasattr(proc, 'isalive'):
        try:
            return bool(proc.isalive())
        except Exception:
            return False
    return bool(proc.poll() is None)


def _append_output(terminal_id, text):
    if not text:
        return
    with terminal_lock:
        item = terminal_processes.get(terminal_id)
        if not item:
            return
        chunks = item.setdefault('output_chunks', [])
        chunks.append(text)
        item['output_size'] = int(item.get('output_size') or 0) + len(text)
        item.setdefault('output_base_offset', 0)
        while chunks and item['output_size'] > MAX_OUTPUT_CHARS:
            removed = chunks.pop(0)
            item['output_size'] -= len(removed)
            item['output_base_offset'] += len(removed)
            item['trimmed'] = True
        item['output'] = ''.join(chunks)


def _reader_thread(terminal_id, proc):
    try:
        if PtyProcess is not None and hasattr(proc, 'read'):
            while _terminal_alive(proc):
                try:
                    chunk = proc.read(4096)
                except EOFError:
                    break
                if chunk:
                    _append_output(terminal_id, chunk)
                else:
                    time.sleep(0.03)
        else:
            stream = getattr(proc, 'stdout', None)
            while True:
                chunk = stream.read(1) if stream else ''
                if not chunk:
                    break
                _append_output(terminal_id, chunk)
    except Exception as exc:
        _append_output(terminal_id, f'\n[terminal reader stopped: {exc}]\n')
    finally:
        _append_output(terminal_id, '\n[process exited]\n')


def _item_payload(terminal_id, item):
    proc = item.get('process')
    pid = None
    if proc:
        pid = getattr(proc, 'pid', None)
    return {
        'id': terminal_id,
        'kind': item.get('kind'),
        'title': item.get('title'),
        'cwd': item.get('cwd'),
        'pid': pid,
        'running': _terminal_alive(proc),
        'created_at': item.get('created_at'),
        'pty': bool(item.get('pty')),
    }


def list_terminals():
    items = []
    for terminal_id, item in list(terminal_processes.items()):
        items.append(_item_payload(terminal_id, item))
    items.sort(key=lambda item: item.get('created_at') or 0, reverse=True)
    return items


def _spawn_pty(args, cwd):
    if PtyProcess is None:
        raise RuntimeError('pywinpty is required for interactive web terminals. Install dependencies with: pip install -e .')
    env = os.environ.copy()
    try:
        from backend.state import get_proxy_api_key
        api_key = get_proxy_api_key()
        env['HTTP_PROXY'] = 'http://127.0.0.1:8317'
        env['HTTPS_PROXY'] = 'http://127.0.0.1:8317'
        env['ANTHROPIC_BASE_URL'] = 'http://127.0.0.1:8317/v1'
        env['ANTHROPIC_API_KEY'] = str(api_key) if api_key else 'cliproxyapi'
    except Exception:
        pass
    return PtyProcess.spawn(args, cwd=cwd, env=env, dimensions=(30, 120))


def _spawn_pipe(args, cwd):
    env = os.environ.copy()
    try:
        from backend.state import get_proxy_api_key
        api_key = get_proxy_api_key()
        env['HTTP_PROXY'] = 'http://127.0.0.1:8317'
        env['HTTPS_PROXY'] = 'http://127.0.0.1:8317'
        env['ANTHROPIC_BASE_URL'] = 'http://127.0.0.1:8317/v1'
        env['ANTHROPIC_API_KEY'] = str(api_key) if api_key else 'cliproxyapi'
    except Exception:
        pass
    return subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
        creationflags=_creationflags(),
    )


def open_terminal(kind='powershell', cwd=None):
    terminal_kind = str(kind or 'powershell').strip().lower()
    if terminal_kind not in ('powershell', 'cmd'):
        raise ValueError('Unsupported terminal type.')

    terminal_id = uuid.uuid4().hex[:8]
    workdir = _terminal_cwd(cwd)
    if terminal_kind == 'cmd':
        title = f'CMD {terminal_id}'
        args = ['cmd.exe', '/D', '/Q', '/K']
    else:
        title = f'PowerShell {terminal_id}'
        command = f"$Host.UI.RawUI.WindowTitle='CLIProxyAPI {title}'; Set-Location -LiteralPath '{workdir}'"
        args = ['powershell.exe', '-NoLogo', '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', command]

    try:
        proc = _spawn_pty(args, workdir)
        is_pty = True
        output = ''
    except Exception as exc:
        proc = _spawn_pipe(args, workdir)
        is_pty = False
        output = f'[PTY unavailable: {exc}]\n交互程序（例如 claude）需要安装 pywinpty 后才能在网页端运行。\n'

    terminal_processes[terminal_id] = {
        'id': terminal_id,
        'kind': terminal_kind,
        'title': title,
        'cwd': workdir,
        'process': proc,
        'created_at': time.time(),
        'output_chunks': [output] if output else [],
        'output_base_offset': 0,
        'output_size': len(output),
        'output': output,
        'trimmed': False,
        'pty': is_pty,
    }
    threading.Thread(target=_reader_thread, args=(terminal_id, proc), daemon=True).start()
    return _item_payload(terminal_id, terminal_processes[terminal_id])


def open_desktop_terminal(kind='powershell', cwd=None):
    terminal_kind = str(kind or 'powershell').strip().lower()
    if terminal_kind not in ('powershell', 'cmd'):
        raise ValueError('Unsupported terminal type.')

    workdir = _terminal_cwd(cwd)
    if os.name == 'nt':
        if terminal_kind == 'cmd':
            args = ['cmd.exe', '/K']
        else:
            args = ['powershell.exe', '-NoLogo', '-NoExit', '-ExecutionPolicy', 'Bypass']
        subprocess.Popen(args, cwd=workdir, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        return {'kind': terminal_kind, 'cwd': workdir}

    shell = os.environ.get('SHELL') or '/bin/sh'
    subprocess.Popen([shell], cwd=workdir, start_new_session=True)
    return {'kind': terminal_kind, 'cwd': workdir}


def read_terminal(terminal_id, offset=0):
    key = str(terminal_id or '').strip()
    item = terminal_processes.get(key)
    if not item:
        raise ValueError('Terminal not found.')
    with terminal_lock:
        chunks = item.get('output_chunks')
        if chunks is None:
            output = item.get('output') or ''
            chunks = [output] if output else []
            item['output_chunks'] = chunks
            item['output_base_offset'] = 0
            item['output_size'] = len(output)
        base_offset = int(item.get('output_base_offset') or 0)
        output = ''.join(chunks)
        end_offset = base_offset + len(output)
        try:
            requested_offset = max(0, int(offset or 0))
        except (TypeError, ValueError):
            requested_offset = 0
        was_trimmed = requested_offset < base_offset or bool(item.get('trimmed'))
        if requested_offset < base_offset:
            start = 0
        else:
            start = max(0, min(requested_offset - base_offset, len(output)))
        result_output = output[start:]
        proc = item.get('process')
        pty = bool(item.get('pty'))
    return {
        'id': key,
        'output': result_output,
        'offset': end_offset,
        'running': _terminal_alive(proc),
        'trimmed': was_trimmed,
        'pty': pty,
    }


def write_terminal(terminal_id, text):
    key = str(terminal_id or '').strip()
    item = terminal_processes.get(key)
    if not item:
        raise ValueError('Terminal not found.')
    proc = item.get('process')
    if not _terminal_alive(proc):
        raise ValueError('Terminal is not running.')
    value = str(text or '')
    if not value:
        return {'id': key, 'running': True}
    if item.get('pty') and hasattr(proc, 'write'):
        proc.write(value)
    else:
        proc.stdin.write(value)
        proc.stdin.flush()
    return {'id': key, 'running': True}


def resize_terminal(terminal_id, rows=None, cols=None):
    key = str(terminal_id or '').strip()
    item = terminal_processes.get(key)
    if not item:
        raise ValueError('Terminal not found.')
    proc = item.get('process')
    if item.get('pty') and hasattr(proc, 'setwinsize'):
        proc.setwinsize(max(2, int(rows or 30)), max(20, int(cols or 120)))
    return {'id': key, 'running': _terminal_alive(proc)}


def close_terminal(terminal_id):
    key = str(terminal_id or '').strip()
    item = terminal_processes.get(key)
    if not item:
        raise ValueError('Terminal not found.')
    proc = item.get('process')
    if proc and _terminal_alive(proc):
        if item.get('pty') and hasattr(proc, 'close'):
            proc.close(force=True)
        elif os.name == 'nt':
            subprocess.run(
                ['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                proc.terminate()
    terminal_processes.pop(key, None)
    return {'id': key, 'running': False}
