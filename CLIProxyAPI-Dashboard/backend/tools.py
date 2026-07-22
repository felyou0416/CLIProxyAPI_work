import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import urllib.request
import urllib.error
import json
import sys
import os
import time
import tempfile
import shutil
import socket
import hashlib
import mimetypes
import re
from urllib.parse import urlparse
from pathlib import Path
from backend.paths import ROOT, PROJECT_ROOT, CLI_EXE, BASE_CONFIG, TOOL_LOGS_DIR, PROVIDER_MODEL_TEST_STATE_FILE, TEMP_DIR, GENERATED_IMAGES_DIR, GENERATED_VIDEOS_DIR
from backend.processes import process_lock, tool_processes, tool_states, process_alive, kill_process, read_tail, _set_tool_state, _tool_log_path
from backend.processes import find_proxy_listener_pid, media_proxy_port, start_media_proxy, wait_for_media_proxy_ready
from backend.processes import probe_socket_stack
from backend.state import load_state, save_state, get_proxy_api_key, normalize_route_strategy
from backend.auth import (
    resolve_auth_reference,
    build_auth_item,
    _read_auth_payload,
    _extract_manual_api_config,
    _group_manual_entry_models,
    collect_provider_model_aliases,
    detect_provider,
    resolve_provider_mapping,
    rewrite_auth_dir,
    rewrite_host,
    rewrite_api_keys,
    rewrite_oauth_model_aliases,
    rewrite_openai_compatibility,
    rewrite_claude_api_key,
    _strip_top_level_block,
    get_configured_provider_models,
    _detect_auth_payload_kind,
    _normalize_runtime_oauth_payload,
    _write_runtime_auth_payload,
    _normalized_auth_file_name,
    _unique_child_path,
    _with_standard_auth_metadata,
    _provider_route_kind,
    derive_global_aggregate_aliases,
    get_configured_aggregate_models,
)

OPENCLAW_CMD = Path.home() / 'AppData' / 'Roaming' / 'npm' / 'openclaw.cmd'
MINIMAX_OAUTH_SCRIPT = ROOT / 'scripts' / 'minimax_oauth_login.py'
CLEANUP_STORAGE_SCRIPT = PROJECT_ROOT / 'scripts' / 'cleanup-storage.ps1'

TOOL_DEFS: dict = {
    'dashboard-script': {'desc': 'Start dashboard PowerShell script', 'cmd_builder': lambda: ['powershell', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'start_dashboard.ps1')]},
    'dashboard-script-open': {'desc': 'Start dashboard PowerShell script and open browser', 'cmd_builder': lambda: ['powershell', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'start_dashboard.ps1'), '-OpenBrowser']},
    'dashboard-bat': {'desc': 'Start dashboard BAT script', 'cmd_builder': lambda: ['cmd', '/c', str(ROOT / 'start_dashboard.bat')]},
    'dashboard-bat-open': {'desc': 'Start dashboard BAT script and open browser', 'cmd_builder': lambda: ['cmd', '/c', str(ROOT / 'start_dashboard.bat'), '/open']},
    'codex-login': {'desc': 'Codex OAuth login', 'cmd_builder': lambda: [str(CLI_EXE), '-codex-login', '-config', str(BASE_CONFIG)]},
    'codex-device-login': {'desc': 'Codex device login', 'cmd_builder': lambda: [str(CLI_EXE), '-codex-device-login', '-config', str(BASE_CONFIG)]},
    'claude-login': {'desc': 'Claude OAuth login', 'cmd_builder': lambda: [str(CLI_EXE), '-claude-login', '-config', str(BASE_CONFIG)]},
    'xai-login': {'desc': 'xAI / Grok OAuth login', 'cmd_builder': lambda: [str(CLI_EXE), '-xai-login', '-config', str(BASE_CONFIG)]},
    'minimax-login-direct': {'desc': 'MiniMax portal OAuth login and save to CLIProxyAPI auth dir', 'cmd_builder': lambda: [sys.executable, str(MINIMAX_OAUTH_SCRIPT)]},
    'login': {'desc': 'Generic OAuth login (Gemini)', 'cmd_builder': lambda: [str(CLI_EXE), '-login', '-config', str(BASE_CONFIG)]},
    'antigravity-login': {'desc': 'Antigravity OAuth login', 'cmd_builder': lambda: [str(CLI_EXE), '-antigravity-login', '-config', str(BASE_CONFIG)]},
    'kimi-login': {'desc': 'Kimi OAuth login', 'cmd_builder': lambda: [str(CLI_EXE), '-kimi-login', '-config', str(BASE_CONFIG)]},
    'tui': {'desc': 'TUI management interface', 'cmd_builder': lambda: [str(CLI_EXE), '-tui', '-standalone', '-config', str(BASE_CONFIG)]},
    'help': {'desc': 'View CLI help', 'cmd_builder': lambda: [str(CLI_EXE), '--help']},
    'vertex-import': {'desc': 'Import Vertex AI service account key', 'cmd_builder': lambda: _vertex_import_cmd()},
}


def _vertex_import_tmp_path():
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_DIR / 'vertex-sa-key.json'


def _vertex_import_cmd():
    tmp_path = _vertex_import_tmp_path()
    if not tmp_path.exists():
        raise FileNotFoundError('Vertex SA key file not found. Upload a JSON key file first.')
    cmd = [str(CLI_EXE), '--vertex-import', str(tmp_path), '-config', str(BASE_CONFIG)]
    state = load_state()
    prefix = (state.get('vertex_import_prefix') or '').strip()
    if prefix:
        cmd.append('--vertex-import-prefix')
        cmd.append(prefix)
    return cmd


def run_vertex_import(file_content: str, prefix: str = ''):
    tmp_path = _vertex_import_tmp_path()
    tmp_path.write_text(file_content, encoding='utf-8')
    if prefix:
        state = load_state()
        state['vertex_import_prefix'] = prefix.strip()
        save_state(state)
    return {'ok': True, 'message': 'Vertex SA key staged for import. Run the vertex-import tool to complete.'}

provider_model_test_lock = threading.Lock()
provider_model_test_worker_running = False
provider_model_test_state = None
PROVIDER_MODEL_TEST_MAX_PARALLEL = 24
PROVIDER_MODEL_TEST_MAX_PER_PROVIDER = 2
PROVIDER_MODEL_TEST_BATCH_PAUSE_SECONDS = 0.2
_LOCAL_URL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _provider_test_parallelism():
    try:
        state = load_state()
        strategy = normalize_route_strategy(state.get('route_strategy'))
        value = int(strategy.get('probe_parallelism') or PROVIDER_MODEL_TEST_MAX_PARALLEL)
        return max(1, min(24, value))
    except Exception:
        return min(24, PROVIDER_MODEL_TEST_MAX_PARALLEL)


def _provider_test_max_per_provider():
    return PROVIDER_MODEL_TEST_MAX_PER_PROVIDER


def _candidate_proxy_api_keys(state=None):
    current_state = state if isinstance(state, dict) else load_state()
    candidates = [
        get_proxy_api_key(current_state),
        current_state.get('last_proxy_api_key'),
        current_state.get('exposure_api_key'),
        'cliproxyapi',
    ]
    unique = []
    for value in candidates:
        key = str(value or '').strip()
        if key and key not in unique:
            unique.append(key)
    return unique


def _provider_call_id_map():
    mapping = {}
    try:
        for item in get_configured_provider_models():
            provider = str(item.get('provider') or '').strip().lower()
            for row in item.get('rows') or []:
                call_id = str(row.get('call_id') or '').strip()
                if call_id and provider and call_id not in mapping:
                    mapping[call_id] = provider
    except Exception:
        return {}
    return mapping


def _provider_for_model_id(model_id: str, call_map: dict[str, str] | None = None):
    call_map = call_map or _provider_call_id_map()
    token = str(model_id or '').strip()
    if not token:
        return ''
    return str(call_map.get(token) or '').strip().lower()


def _select_provider_test_batch(model_ids: list[str], max_parallel: int):
    pending = [str(item or '').strip() for item in (model_ids or []) if str(item or '').strip()]
    if not pending:
        return [], []

    call_map = _provider_call_id_map()
    per_provider_limit = max(1, _provider_test_max_per_provider())
    chosen = []
    remaining = []
    counts = defaultdict(int)

    for model_id in pending:
        provider = _provider_for_model_id(model_id, call_map) or f'__unknown__:{model_id}'
        if len(chosen) < max_parallel and counts[provider] < per_provider_limit:
            chosen.append(model_id)
            counts[provider] += 1
        else:
            remaining.append(model_id)
    return chosen, remaining


def _default_provider_model_test_state():
    return {
        'results': {},
        'test_counts': {},
        'running': [],
        'queue': [],
        'cancel_requested': False,
        'updated_at': 0,
    }


def _sanitize_provider_model_test_state(state: dict):
    if not isinstance(state, dict):
        return _default_provider_model_test_state()

    now = int(time.time())
    results = state.get('results') if isinstance(state.get('results'), dict) else {}
    test_counts = state.get('test_counts') if isinstance(state.get('test_counts'), dict) else {}
    queue = [str(value or '').strip() for value in (state.get('queue') if isinstance(state.get('queue'), list) else []) if str(value or '').strip()]
    running = [str(value or '').strip() for value in (state.get('running') if isinstance(state.get('running'), list) else []) if str(value or '').strip()]
    cancel_requested = bool(state.get('cancel_requested'))
    updated_at = int(state.get('updated_at') or 0)

    cleaned_running = []
    changed = False
    stale_cutoff = 180

    for model_id in running:
      item = results.get(model_id) if isinstance(results.get(model_id), dict) else {}
      item_status = str(item.get('status') or '').strip().lower()
      tested_at = int(item.get('tested_at') or 0)
      has_final_result = bool(item) and item_status != 'testing'

      if has_final_result:
          changed = True
          continue

      is_stale = False
      if not provider_model_test_worker_running:
          if tested_at and (now - tested_at) > stale_cutoff:
              is_stale = True
          elif updated_at and (now - updated_at) > stale_cutoff:
              is_stale = True

      if is_stale:
          results[model_id] = {
              'model': model_id,
              'available': False,
              'working_path': None,
              'status_code': None,
              'message': 'Stale test state cleared automatically.',
              'elapsed_ms': None,
              'retry_after_seconds': 0,
              'failure_kind': 'timeout',
              'tested_at': now,
          }
          changed = True
          continue

      cleaned_running.append(model_id)

    if changed or len(cleaned_running) != len(running) or len(queue) != len(state.get('queue', [])):
        state['results'] = results
        state['test_counts'] = _sanitize_provider_model_test_counts(test_counts)
        state['queue'] = queue
        state['running'] = cleaned_running
        state['cancel_requested'] = cancel_requested
        state['updated_at'] = now
    else:
        state['test_counts'] = _sanitize_provider_model_test_counts(test_counts)
        state['cancel_requested'] = cancel_requested
    return state


def _sanitize_provider_model_test_counts(value: dict):
    if not isinstance(value, dict):
        return {}
    cleaned = {}
    for model_id, item in value.items():
        model_value = str(model_id or '').strip()
        if not model_value:
            continue
        if not isinstance(item, dict):
            continue
        total = max(0, int(item.get('total') or 0))
        success = max(0, int(item.get('success') or 0))
        failure = max(0, int(item.get('failure') or 0))
        if total < success + failure:
            total = success + failure
        cleaned[model_value] = {
            'total': total,
            'success': success,
            'failure': failure,
            'last_tested_at': int(item.get('last_tested_at') or 0),
        }
    return cleaned


def _record_provider_model_test_count(state: dict, item: dict):
    model_id = str((item or {}).get('model') or '').strip()
    if not model_id:
        return
    counts = state.setdefault('test_counts', {})
    current = counts.get(model_id) if isinstance(counts.get(model_id), dict) else {}
    total = int(current.get('total') or 0) + 1
    success = int(current.get('success') or 0)
    failure = int(current.get('failure') or 0)
    if bool((item or {}).get('available')):
        success += 1
    else:
        failure += 1
    counts[model_id] = {
        'total': total,
        'success': success,
        'failure': failure,
        'last_tested_at': int((item or {}).get('tested_at') or time.time()),
    }


def _load_provider_model_test_state():
    global provider_model_test_state
    if provider_model_test_state is not None:
        provider_model_test_state = _sanitize_provider_model_test_state(provider_model_test_state)
        return provider_model_test_state
    try:
        if PROVIDER_MODEL_TEST_STATE_FILE.exists():
            data = json.loads(PROVIDER_MODEL_TEST_STATE_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                state = _default_provider_model_test_state()
                state['results'] = data.get('results') if isinstance(data.get('results'), dict) else {}
                state['test_counts'] = data.get('test_counts') if isinstance(data.get('test_counts'), dict) else {}
                state['running'] = data.get('running') if isinstance(data.get('running'), list) else []
                state['queue'] = data.get('queue') if isinstance(data.get('queue'), list) else []
                state['updated_at'] = int(data.get('updated_at') or 0)
                provider_model_test_state = _sanitize_provider_model_test_state(state)
                return provider_model_test_state
    except Exception:
        pass
    provider_model_test_state = _sanitize_provider_model_test_state(_default_provider_model_test_state())
    return provider_model_test_state


def _save_provider_model_test_state():
    state = _load_provider_model_test_state()
    state['updated_at'] = int(time.time())
    PROVIDER_MODEL_TEST_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def get_provider_model_test_state():
    with provider_model_test_lock:
        state = _load_provider_model_test_state()
        return {
            'ok': True,
            'results': state.get('results', {}),
            'test_counts': state.get('test_counts', {}),
            'running': list(state.get('running', [])),
            'queue': list(state.get('queue', [])),
            'updated_at': state.get('updated_at', 0),
        }


def _run_external_tool(tool_id: str, cmd: list, cwd: str, start_event: threading.Event, start_result: dict):
    stdout_path = _tool_log_path(TOOL_LOGS_DIR, tool_id, 'stdout')
    stderr_path = _tool_log_path(TOOL_LOGS_DIR, tool_id, 'stderr')
    try:
        with open(stdout_path, 'w', encoding='utf-8', errors='ignore') as fout, open(stderr_path, 'w', encoding='utf-8', errors='ignore') as ferr:
            creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            proc = subprocess.Popen(cmd, cwd=cwd, stdout=fout, stderr=ferr, stdin=subprocess.DEVNULL, creationflags=creationflags)
            with process_lock:
                tool_processes[tool_id] = proc
            _set_tool_state(tool_id, running=True, pid=proc.pid, error=None)
            start_result['ok'] = True
            start_result['pid'] = proc.pid
            start_event.set()
            proc.wait()
            _set_tool_state(tool_id, running=False, returncode=proc.returncode, error=None)
    except Exception as e:
        with open(stdout_path, 'w', encoding='utf-8', errors='ignore') as f:
            f.write(f'Error: {e}')
        start_result['error'] = str(e)
        start_event.set()
        _set_tool_state(tool_id, running=False, error=str(e))


def run_tool(tool_id: str):
    if tool_id not in TOOL_DEFS:
        return {'ok': False, 'message': f'Unknown tool: {tool_id}'}
    with process_lock:
        proc = tool_processes.get(tool_id)
        if process_alive(proc):
            return {'ok': False, 'message': f'{TOOL_DEFS[tool_id]["desc"]} is already running.'}
        if proc is not None and not process_alive(proc):
            tool_processes.pop(tool_id, None)
    cmd = TOOL_DEFS[tool_id]['cmd_builder']()
    start_event = threading.Event()
    start_result = {}
    t = threading.Thread(target=_run_external_tool, args=(tool_id, cmd, str(PROJECT_ROOT), start_event, start_result), daemon=True)
    t.start()
    started = start_event.wait(timeout=5)
    if not started:
        return {'ok': False, 'message': 'Timed out while starting tool.'}
    if start_result.get('error'):
        return {'ok': False, 'message': f'Failed to start tool: {start_result["error"]}'}
    return {'ok': True, 'message': f'Started: {TOOL_DEFS[tool_id]["desc"]}', 'pid': start_result.get('pid')}


def run_storage_cleanup(
    apply: bool = False,
    include_logs: bool = False,
    include_archived_error_logs: bool = False,
    include_backups: bool = False,
    include_generated_images: bool = False,
    include_old_auth: bool = False,
) -> dict:
    if not CLEANUP_STORAGE_SCRIPT.exists():
        return {'ok': False, 'message': f'Cleanup script not found: {CLEANUP_STORAGE_SCRIPT}'}
    cmd = [
        'powershell',
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        str(CLEANUP_STORAGE_SCRIPT),
    ]
    if apply:
        cmd.append('-Apply')
    if include_logs:
        cmd.append('-IncludeLogs')
    if include_archived_error_logs:
        cmd.append('-IncludeArchivedErrorLogs')
    if include_backups:
        cmd.append('-IncludeBackups')
    if include_generated_images:
        cmd.append('-IncludeGeneratedImages')
    if include_old_auth:
        cmd.append('-IncludeOldAuth')

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120,
        )
    except Exception as exc:
        return {'ok': False, 'message': f'Cleanup failed: {exc}'}

    output = '\n'.join(part for part in (proc.stdout, proc.stderr) if part).strip()
    return {
        'ok': proc.returncode == 0,
        'message': 'Cleanup completed.' if apply else 'Cleanup preview completed.',
        'returncode': proc.returncode,
        'output': output,
    }


def stop_tool(tool_id: str):
    with process_lock:
        proc = tool_processes.get(tool_id)
    if proc is None or not process_alive(proc):
        _set_tool_state(tool_id, running=False, error=None)
        return {'ok': True, 'message': f'{tool_id} is not running.'}
    stopped = kill_process(proc)
    _set_tool_state(tool_id, running=False, error='Stopped by user', returncode=None)
    return {'ok': True, 'message': f'Stopped {tool_id}.' if stopped else f'Could not stop {tool_id}.'}


def get_tool_outputs():
    outputs = {}
    running = {}
    states = {}
    for tool_id in TOOL_DEFS:
        stdout_path = _tool_log_path(TOOL_LOGS_DIR, tool_id, 'stdout')
        stderr_path = _tool_log_path(TOOL_LOGS_DIR, tool_id, 'stderr')
        out = read_tail(stdout_path, 3000)
        err = read_tail(stderr_path, 1000)
        combined = '\n'.join(x for x in [out, ('\n[stderr]\n' + err if err else '')] if x)
        outputs[tool_id] = combined if combined else None
        state = tool_states.get(tool_id, {'running': False, 'returncode': None, 'error': None, 'pid': None})
        running[tool_id] = bool(state.get('running'))
        states[tool_id] = state
    return {'outputs': outputs, 'running': running, 'states': states}


_cached_query_models_result = None
_cached_query_models_time = 0.0


def query_models():
    global _cached_query_models_result, _cached_query_models_time
    now = time.monotonic()
    if _cached_query_models_result is not None and (now - _cached_query_models_time) < 5.0:
        return _cached_query_models_result

    last_failure = None
    for api_key in _candidate_proxy_api_keys():
        try:
            req = urllib.request.Request('http://127.0.0.1:8317/v1/models', headers={'Authorization': f'Bearer {api_key}'}, method='GET')
            with _LOCAL_URL_OPENER.open(req, timeout=2) as resp:
                body = resp.read().decode('utf-8', errors='ignore')
                res = {'ok': True, 'status_code': 200, 'body': json.loads(body)}
                _cached_query_models_result = res
                _cached_query_models_time = now
                return res
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='ignore')[:500]
            last_failure = {'ok': False, 'status_code': e.code, 'body': body}
            if e.code not in (401, 403):
                break
        except Exception as e:
            last_failure = {'ok': False, 'error': str(e)}
            break
    res = last_failure or {'ok': False, 'error': 'No proxy API key candidates available.'}
    _cached_query_models_result = res
    _cached_query_models_time = now
    return res


def test_proxy():
    body = json.dumps({'model': 'gpt-5-codex', 'input': 'Say OK only.'}).encode('utf-8')
    last_failure = None
    for api_key in _candidate_proxy_api_keys():
        try:
            req = urllib.request.Request('http://127.0.0.1:8317/v1/responses', data=body, headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}, method='POST')
            with _LOCAL_URL_OPENER.open(req, timeout=15) as resp:
                response_body = resp.read().decode('utf-8', errors='ignore')
                return {'ok': True, 'status_code': 200, 'body': json.loads(response_body)}
        except urllib.error.HTTPError as e:
            response_body = e.read().decode('utf-8', errors='ignore')[:500]
            last_failure = {'ok': False, 'status_code': e.code, 'body': response_body}
            if e.code not in (401, 403):
                break
        except Exception as e:
            last_failure = {'ok': False, 'error': str(e)}
            break
    return last_failure or {'ok': False, 'error': 'No proxy API key candidates available.'}


def _raw_media_model_kind(*model_ids):
    token = ' '.join(str(model_id or '').strip().lower() for model_id in model_ids if str(model_id or '').strip())
    if not token:
        return ''
    if 'image' in token or 'gpt-image' in token:
        return 'image'
    if 'video' in token or token.startswith('sora'):
        return 'video'
    return ''


def _media_request_path_kind(path: str):
    request_path = str(path or '').strip().lower()
    if request_path.startswith('/v1/images/'):
        return 'image'
    if request_path == '/v1/videos' or request_path.startswith('/v1/videos/'):
        return 'video'
    return ''


def _resolve_provider_media_model(model_id: str, desired_kind: str = ''):
    model_value = str(model_id or '').strip()
    if not model_value:
        return None
    for item in get_configured_provider_models():
        for row in item.get('rows') or []:
            call_id = str(row.get('call_id') or row.get('alias') or row.get('name') or '').strip()
            upstream_id = str(row.get('upstream_id') or '').strip()
            lookup_upstream_id = str(row.get('lookup_upstream_id') or '').strip()
            runtime_upstream_id = str(row.get('runtime_upstream_id') or upstream_id or '').strip()
            candidates = {item for item in [call_id, upstream_id, lookup_upstream_id, runtime_upstream_id] if item}
            if model_value not in candidates:
                continue
            kind = _raw_media_model_kind(upstream_id, runtime_upstream_id, lookup_upstream_id, call_id)
            if not kind or (desired_kind and kind != desired_kind):
                continue
            return {
                'kind': kind,
                'model': upstream_id or runtime_upstream_id or lookup_upstream_id or call_id,
                'source': 'provider-model',
            }
    return None


def _resolve_aggregate_media_model(model_id: str, desired_kind: str = ''):
    model_value = str(model_id or '').strip()
    if not model_value:
        return None
    for aggregate in get_configured_aggregate_models():
        alias_id = str(aggregate.get('alias_id') or '').strip()
        if alias_id != model_value or aggregate.get('enabled') is False:
            continue
        for member in aggregate.get('members') or []:
            call_id = str(member.get('call_id') or '').strip()
            upstream_id = str(member.get('upstream_id') or '').strip()
            runtime_upstream_id = str(member.get('runtime_upstream_id') or upstream_id or '').strip()
            kind = _raw_media_model_kind(runtime_upstream_id, upstream_id, call_id)
            if not kind or (desired_kind and kind != desired_kind):
                continue
            return {
                'kind': kind,
                'model': runtime_upstream_id or upstream_id or call_id,
                'source': 'aggregate-model',
            }
    return None


def _resolve_media_proxy_payload(path: str, payload: dict):
    request_path = str(path or '').strip().lower()
    desired_kind = _media_request_path_kind(request_path)
    model_value = str((payload or {}).get('model') or '').strip()
    resolution = (
        _resolve_aggregate_media_model(model_value, desired_kind)
        or _resolve_provider_media_model(model_value, desired_kind)
    )
    if not resolution:
        raw_kind = _raw_media_model_kind(model_value)
        aggregate_only_names = {'auto', 'image', 'agent', 'coder', 'reasoning', 'chat'}
        if model_value.lower() not in aggregate_only_names and raw_kind and (not desired_kind or raw_kind == desired_kind):
            resolution = {'kind': raw_kind, 'model': model_value, 'source': 'raw-name'}
    if not resolution:
        if desired_kind:
            return True, dict(payload or {})
        return False, dict(payload or {})
    if request_path == '/v1/chat/completions' and not resolution.get('kind'):
        return False, dict(payload or {})
    next_payload = dict(payload or {})
    if resolution.get('model'):
        next_payload['model'] = resolution['model']
    return True, next_payload


def _is_media_proxy_request(path: str, payload: dict):
    return _resolve_media_proxy_payload(path, payload)[0]


def _ensure_media_proxy_running():
    if find_proxy_listener_pid(media_proxy_port()):
        return {'ok': True, 'already_running': True}
    result = start_media_proxy()
    if not result.get('ok'):
        return result
    if not wait_for_media_proxy_ready():
        return {'ok': False, 'message': 'Media proxy start command was sent, but port 8320 did not become ready in time.'}
    return {**result, 'already_running': False}


IMAGE_URL_RE = re.compile(r'https?://[^\s)"\']+\.(?:png|jpe?g|webp)(?:\?[^\s)"\']*)?', re.IGNORECASE)
MAX_GENERATED_IMAGES = 50
MAX_GENERATED_VIDEOS = 30
MAX_MEDIA_PROXY_BYTES = 120 * 1024 * 1024


def _generated_image_ext(url: str, content_type: str = ''):
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext in ('.png', '.jpg', '.jpeg', '.webp'):
        return ext
    guessed = mimetypes.guess_extension((content_type or '').split(';', 1)[0].strip())
    return guessed if guessed in ('.png', '.jpg', '.jpeg', '.webp') else '.png'


def _generated_video_ext(url: str, content_type: str = ''):
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext in ('.mp4', '.webm', '.mov', '.m4v', '.mkv'):
        return ext
    ctype = (content_type or '').split(';', 1)[0].strip().lower()
    mapping = {
        'video/mp4': '.mp4',
        'video/webm': '.webm',
        'video/quicktime': '.mov',
        'video/x-m4v': '.m4v',
        'video/x-matroska': '.mkv',
    }
    if ctype in mapping:
        return mapping[ctype]
    guessed = mimetypes.guess_extension(ctype)
    return guessed if guessed in ('.mp4', '.webm', '.mov', '.m4v', '.mkv') else '.mp4'


def validate_remote_media_url(url: str) -> str:
    value = str(url or '').strip()
    if not value:
        raise ValueError('Media URL is required.')
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError('Only http(s) media URLs are allowed.')
    if not parsed.netloc:
        raise ValueError('Media URL host is missing.')
    return value


def _cleanup_generated_videos(limit: int = MAX_GENERATED_VIDEOS):
    try:
        files = [
            path for path in GENERATED_VIDEOS_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in ('.mp4', '.webm', '.mov', '.m4v', '.mkv')
        ]
    except FileNotFoundError:
        return
    overflow = len(files) - max(0, int(limit))
    if overflow <= 0:
        return
    files.sort(key=lambda path: path.stat().st_mtime)
    for path in files[:overflow]:
        try:
            path.unlink()
        except Exception:
            pass


def fetch_remote_media(url: str, *, timeout: int = 120) -> dict:
    remote = validate_remote_media_url(url)
    req = urllib.request.Request(
        remote,
        headers={
            'User-Agent': 'CLIProxyAPI-Dashboard/1.0',
            'Accept': 'video/*,application/octet-stream,*/*',
        },
        method='GET',
    )
    try:
        with _LOCAL_URL_OPENER.open(req, timeout=timeout) as resp:
            content_type = resp.headers.get('Content-Type', '') or 'application/octet-stream'
            chunks = []
            total = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_MEDIA_PROXY_BYTES:
                    raise ValueError(f'Media exceeds {MAX_MEDIA_PROXY_BYTES} bytes.')
                chunks.append(chunk)
            data = b''.join(chunks)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'Upstream media HTTP {exc.code}') from exc
    except Exception as exc:
        raise ValueError(f'Failed to fetch media: {exc}') from exc
    if not data:
        raise ValueError('Upstream media response was empty.')
    return {
        'url': remote,
        'data': data,
        'content_type': content_type,
        'ext': _generated_video_ext(remote, content_type),
    }


def materialize_generated_video(url: str) -> dict:
    remote = validate_remote_media_url(url)
    GENERATED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(remote.encode('utf-8')).hexdigest()[:16]
    existing = sorted(GENERATED_VIDEOS_DIR.glob(f'*-{digest}.*'))
    for path in existing:
        if path.is_file() and path.stat().st_size > 0:
            content_type = mimetypes.guess_type(path.name)[0] or 'video/mp4'
            return {
                'ok': True,
                'remote_url': remote,
                'local_url': f'/generated/videos/{path.name}',
                'path': path,
                'absolute_path': str(path),
                'content_type': content_type,
                'filename': path.name,
                'cached': True,
            }
    fetched = fetch_remote_media(remote)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    filename = f'{stamp}-{digest}{fetched["ext"]}'
    target = GENERATED_VIDEOS_DIR / filename
    target.write_bytes(fetched['data'])
    _cleanup_generated_videos()
    content_type = fetched.get('content_type') or (mimetypes.guess_type(filename)[0] or 'video/mp4')
    return {
        'ok': True,
        'remote_url': remote,
        'local_url': f'/generated/videos/{filename}',
        'path': target,
        'absolute_path': str(target),
        'content_type': content_type,
        'filename': filename,
        'cached': False,
        'bytes': len(fetched['data']),
    }


def resolve_generated_media_path(path_or_url: str) -> Path:
    value = str(path_or_url or '').strip()
    if not value:
        raise ValueError('Media path is required.')

    # Allow bare storage roots / prefixes for "open save folder".
    normalized = value.rstrip('/')
    if value in ('/generated/images', '/generated/images/') or normalized == '/generated/images':
        return GENERATED_IMAGES_DIR.resolve()
    if value in ('/generated/videos', '/generated/videos/') or normalized == '/generated/videos':
        return GENERATED_VIDEOS_DIR.resolve()

    roots = (
        ('/generated/images/', GENERATED_IMAGES_DIR),
        ('/generated/videos/', GENERATED_VIDEOS_DIR),
    )
    for prefix, root in roots:
        if value.startswith(prefix):
            rel = value[len(prefix):].split('?', 1)[0].split('#', 1)[0]
            try:
                from urllib.parse import unquote as _unquote
                rel = _unquote(rel)
            except Exception:
                pass
            rel = rel.replace('\\', '/').lstrip('/')
            if not rel:
                return root.resolve()
            if '..' in Path(rel).parts:
                raise ValueError('Invalid media path.')
            target = (root / rel).resolve()
            base = root.resolve()
            try:
                target.relative_to(base)
            except ValueError as exc:
                raise ValueError('Path is outside generated media storage.') from exc
            return target

    candidate = Path(value).expanduser()
    try:
        target = candidate.resolve()
    except Exception as exc:
        raise ValueError(f'Invalid local path: {exc}') from exc
    for root in (GENERATED_IMAGES_DIR, GENERATED_VIDEOS_DIR):
        base = root.resolve()
        try:
            target.relative_to(base)
            return target
        except ValueError:
            continue
    raise ValueError('Only generated image/video storage paths can be revealed.')


def list_generated_media(kind: str = 'all', limit: int = 200) -> dict:
    """List files under generated image/video storage for cross-client gallery."""
    kind_value = str(kind or 'all').strip().lower()
    if kind_value not in ('all', 'image', 'images', 'video', 'videos'):
        kind_value = 'all'
    try:
        max_items = max(1, min(int(limit or 200), 500))
    except (TypeError, ValueError):
        max_items = 200

    image_exts = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg'}
    video_exts = {'.mp4', '.webm', '.mov', '.m4v', '.mkv'}
    items = []

    def collect(root: Path, media_kind: str, url_prefix: str, exts: set[str]):
        try:
            entries = [path for path in root.iterdir() if path.is_file() and path.suffix.lower() in exts]
        except FileNotFoundError:
            return
        for path in entries:
            try:
                stat = path.stat()
            except OSError:
                continue
            items.append({
                'kind': media_kind,
                'filename': path.name,
                'url': f'{url_prefix}{path.name}',
                'bytes': int(stat.st_size),
                'mtime': int(stat.st_mtime),
                'absolute_path': str(path.resolve()),
            })

    if kind_value in ('all', 'image', 'images'):
        collect(GENERATED_IMAGES_DIR, 'image', '/generated/images/', image_exts)
    if kind_value in ('all', 'video', 'videos'):
        collect(GENERATED_VIDEOS_DIR, 'video', '/generated/videos/', video_exts)

    items.sort(key=lambda item: (int(item.get('mtime') or 0), str(item.get('filename') or '')), reverse=True)
    trimmed = items[:max_items]
    return {
        'ok': True,
        'kind': kind_value,
        'count': len(trimmed),
        'total': len(items),
        'items': trimmed,
        'images_dir': str(GENERATED_IMAGES_DIR.resolve()),
        'videos_dir': str(GENERATED_VIDEOS_DIR.resolve()),
    }


def reveal_generated_media(path_or_url: str) -> dict:
    target = resolve_generated_media_path(path_or_url)
    if not target.exists():
        # Allow opening storage roots even if empty; only fail for missing files.
        if target.suffix:
            raise ValueError('Media file not found on disk.')
        target.mkdir(parents=True, exist_ok=True)
    folder = target if target.is_dir() else target.parent
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == 'nt':
            if target.is_file():
                subprocess.Popen(['explorer', f'/select,{str(target)}'])
            else:
                subprocess.Popen(['explorer', str(folder)])
        elif sys.platform == 'darwin':
            if target.is_file():
                subprocess.Popen(['open', '-R', str(target)])
            else:
                subprocess.Popen(['open', str(folder)])
        else:
            subprocess.Popen(['xdg-open', str(folder)])
    except Exception as exc:
        raise ValueError(f'Failed to open folder: {exc}') from exc
    return {
        'ok': True,
        'path': str(target),
        'folder': str(folder),
        'exists': target.exists(),
    }


def _cleanup_generated_images(limit: int = MAX_GENERATED_IMAGES):
    try:
        files = [
            path for path in GENERATED_IMAGES_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
        ]
    except FileNotFoundError:
        return
    overflow = len(files) - max(0, int(limit))
    if overflow <= 0:
        return
    files.sort(key=lambda path: path.stat().st_mtime)
    for path in files[:overflow]:
        try:
            path.unlink()
        except Exception:
            pass


def _download_generated_image(url: str):
    url_value = str(url or '').strip()
    if not url_value:
        return ''
    GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url_value.encode('utf-8')).hexdigest()[:16]
    stamp = time.strftime('%Y%m%d-%H%M%S')
    try:
        req = urllib.request.Request(url_value, headers={'User-Agent': 'CLIProxyAPI-Dashboard/1.0'}, method='GET')
        with _LOCAL_URL_OPENER.open(req, timeout=45) as resp:
            content_type = resp.headers.get('Content-Type', '')
            data = resp.read()
    except Exception:
        return ''
    if not data:
        return ''
    ext = _generated_image_ext(url_value, content_type)
    target = GENERATED_IMAGES_DIR / f'{stamp}-{digest}{ext}'
    try:
        target.write_bytes(data)
        _cleanup_generated_images()
    except Exception:
        return ''
    return f'/generated/images/{target.name}'


def _localize_generated_images(body: str):
    try:
        payload = json.loads(body or '{}')
    except Exception:
        return body
    replacements = {}

    def local_url(remote_url: str):
        remote = str(remote_url or '').strip()
        if not remote:
            return ''
        if remote not in replacements:
            replacements[remote] = _download_generated_image(remote)
        return replacements.get(remote) or ''

    def walk(value):
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if key in ('url', 'image_url') and isinstance(item, str) and IMAGE_URL_RE.match(item):
                    saved = local_url(item)
                    if saved:
                        value.setdefault('remote_url', item)
                        value[key] = saved
                    continue
                if key == 'content' and isinstance(item, str):
                    def replace_match(match):
                        saved = local_url(match.group(0))
                        return saved or match.group(0)
                    value[key] = IMAGE_URL_RE.sub(replace_match, item)
                    continue
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def _proxy_request(path: str, payload: dict, timeout: int = 60):
    api_key = get_proxy_api_key(load_state())
    base_url = 'http://127.0.0.1:8317'
    is_media_request, request_payload = _resolve_media_proxy_payload(path, payload)
    if is_media_request:
        ensure_result = _ensure_media_proxy_running()
        if not ensure_result.get('ok'):
            return {'ok': False, 'error': ensure_result.get('message') or 'Media proxy is not available.', 'elapsed_ms': 0}
        base_url = f'http://127.0.0.1:{media_proxy_port()}'
    req = urllib.request.Request(
        f'{base_url}{path}',
        data=json.dumps(request_payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    started_at = time.monotonic()
    try:
        with _LOCAL_URL_OPENER.open(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
            if is_media_request:
                body = _localize_generated_images(body)
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            return {'ok': True, 'status_code': resp.status, 'body': body, 'elapsed_ms': elapsed_ms}
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='ignore')
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        return {'ok': False, 'status_code': e.code, 'body': body, 'elapsed_ms': elapsed_ms}
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        return {'ok': False, 'error': str(e), 'elapsed_ms': elapsed_ms}


def _request_with_api_key(base_url: str, path: str, payload: dict, api_key: str, timeout: int = 60):
    req = urllib.request.Request(
        f'{base_url}{path}',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    started_at = time.monotonic()
    try:
        with _LOCAL_URL_OPENER.open(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            return {'ok': True, 'status_code': resp.status, 'body': body, 'elapsed_ms': elapsed_ms}
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='ignore')
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        return {'ok': False, 'status_code': e.code, 'body': body, 'elapsed_ms': elapsed_ms}
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        return {'ok': False, 'error': str(e), 'elapsed_ms': elapsed_ms}


def _find_free_port():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(('127.0.0.1', 0))
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return sock.getsockname()[1]
    except OSError as exc:
        win_error = getattr(exc, 'winerror', None)
        if win_error == 10106:
            raise RuntimeError('Local socket stack is unavailable (Winsock WinError 10106). Run an elevated "netsh winsock reset", then reboot Windows.') from exc
        raise


def _rewrite_port(config_text: str, port: int):
    port_value = int(port or 8317)
    lines = config_text.splitlines()
    replaced = False
    output = []
    for line in lines:
        if line.strip().startswith('port:'):
            output.append(f'port: {port_value}')
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f'port: {port_value}')
    return '\n'.join(output) + '\n'


def _probe_proxy_ready(base_url: str, api_key: str, timeout_seconds: int = 20):
    deadline = time.monotonic() + timeout_seconds
    req = urllib.request.Request(
        f'{base_url}/v1/models',
        headers={'Authorization': f'Bearer {api_key}'},
        method='GET',
    )
    last_error = None
    while time.monotonic() < deadline:
        try:
            with _LOCAL_URL_OPENER.open(req, timeout=5) as resp:
                if resp.status == 200:
                    return True, None
        except Exception as e:
            last_error = str(e)
        time.sleep(0.5)
    return False, last_error or 'Timed out while waiting for temporary proxy.'


def _build_temp_auth_runtime(auth_ref: str, temp_root: Path, bind_port: int, access_api_key: str):
    active_auth_dir = temp_root / 'active-auth'
    active_auth_dir.mkdir(parents=True, exist_ok=True)
    config_text = BASE_CONFIG.read_text(encoding='utf-8', errors='ignore')
    config_text = rewrite_host(config_text, '127.0.0.1')
    config_text = _rewrite_port(config_text, bind_port)
    config_text = rewrite_auth_dir(config_text, active_auth_dir)
    
    # Merge admin access key with all active virtual API keys
    all_api_keys = [access_api_key]
    try:
        from backend.api_keys import get_all_active_key_values
        virtual_key_values = get_all_active_key_values()
        for vk in virtual_key_values:
            if vk and vk not in all_api_keys:
                all_api_keys.append(vk)
    except Exception:
        pass
    config_text = rewrite_api_keys(config_text, all_api_keys)

    resolved = resolve_auth_reference(auth_ref=auth_ref)
    if not resolved:
        raise FileNotFoundError(f'Auth entry not found: {auth_ref}')
    source_id, source = resolved
    payload = _read_auth_payload(source)
    manual_entry = _extract_manual_api_config(payload, source.name)

    if manual_entry:
        if manual_entry.get('api') == 'anthropic-messages':
            config_text = rewrite_claude_api_key(config_text, [manual_entry])
            config_text = _strip_top_level_block(config_text, 'openai-compatibility')
        else:
            config_text = rewrite_openai_compatibility(config_text, [manual_entry])
            config_text = _strip_top_level_block(config_text, 'claude-api-key')
        config_text = _strip_top_level_block(config_text, 'oauth-model-alias')
        grouped = _group_manual_entry_models(manual_entry)
        candidate_models = []
        for models in grouped.values():
            for model in models:
                alias = str(model.get('alias') or '').strip()
                if alias and alias not in candidate_models:
                    candidate_models.append(alias)
        item = build_auth_item(source_id, source)
        return config_text, candidate_models, item

    provider = detect_provider(payload, source.name)
    auth_kind = _detect_auth_payload_kind(payload)
    normalized_payload = _normalize_runtime_oauth_payload(payload, provider, auth_kind)
    payload_for_name = normalized_payload if isinstance(normalized_payload, dict) else payload
    runtime_name = _normalized_auth_file_name(provider, payload_for_name, source.name)
    runtime_path = _unique_child_path(active_auth_dir, runtime_name, source)
    if normalized_payload:
        normalized_payload = _with_standard_auth_metadata(
            normalized_payload,
            provider,
            source.name,
            'dashboard_temp_test',
        )
        _write_runtime_auth_payload(runtime_path, normalized_payload)
    else:
        if isinstance(payload, dict):
            _write_runtime_auth_payload(
                runtime_path,
                _with_standard_auth_metadata(payload, provider, source.name, 'dashboard_temp_test'),
            )
        else:
            shutil.copy2(source, runtime_path)
    config_text = rewrite_openai_compatibility(_strip_top_level_block(config_text, 'openai-compatibility'), [])
    config_text = rewrite_claude_api_key(_strip_top_level_block(config_text, 'claude-api-key'), [])
    config_text = rewrite_oauth_model_aliases(config_text, [provider], auth_refs=[auth_ref])
    alias_map = collect_provider_model_aliases(auth_refs=[auth_ref])
    candidate_models = []
    for model_name, alias in alias_map.get(provider, []):
        mapping = resolve_provider_mapping(provider, model_name, alias)
        candidate_value = str(mapping.get('call_id') or alias or model_name or '').strip()
        if candidate_value and candidate_value not in candidate_models:
            candidate_models.append(candidate_value)
    item = build_auth_item(source_id, source)
    return config_text, candidate_models, item


def test_auth_entry(auth_ref: str):
    auth_ref = str(auth_ref or '').strip()
    if not auth_ref:
        return {'ok': False, 'message': 'auth_ref is required.'}
    socket_issue = probe_socket_stack()
    if socket_issue:
        return {
            'ok': False,
            'auth_ref': auth_ref,
            'available': False,
            'message': socket_issue,
            'retry_after_seconds': 0,
            'failure_kind': 'infrastructure',
            'tested_at': int(time.time()),
        }

    temp_api_key = 'cliproxyapi-auth-test'
    temp_port = _find_free_port()
    temp_base_url = f'http://127.0.0.1:{temp_port}'

    with tempfile.TemporaryDirectory(prefix='auth-test-', dir=str(TEMP_DIR)) as temp_dir:
        temp_root = Path(temp_dir)
        stdout_path = temp_root / 'proxy.stdout.log'
        stderr_path = temp_root / 'proxy.stderr.log'
        config_path = temp_root / 'cliproxyapi-test-config.yaml'
        proc = None
        try:
            config_text, candidate_models, item = _build_temp_auth_runtime(auth_ref, temp_root, temp_port, temp_api_key)
            if not candidate_models:
                return {'ok': False, 'message': 'No candidate models found for this auth entry.'}
            config_path.write_text(config_text, encoding='utf-8')

            with open(stdout_path, 'w', encoding='utf-8', errors='ignore') as fout, open(stderr_path, 'w', encoding='utf-8', errors='ignore') as ferr:
                creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                proc = subprocess.Popen(
                    [str(CLI_EXE), '-config', str(config_path)],
                    cwd=str(PROJECT_ROOT),
                    stdout=fout,
                    stderr=ferr,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags,
                )

            ready, ready_error = _probe_proxy_ready(temp_base_url, temp_api_key)
            if not ready:
                return {
                    'ok': False,
                    'auth_ref': auth_ref,
                    'auth_name': item.get('name'),
                    'available': False,
                    'message': ready_error or 'Temporary proxy did not become ready.',
                    'retry_after_seconds': 120,
                    'tested_at': int(time.time()),
                    'stderr': read_tail(stderr_path, 1200),
                }

            attempts = []
            success = None
            for model_id in candidate_models:
                for check in _candidate_checks_for_model(model_id):
                    result = _request_with_api_key(temp_base_url, check['path'], check['payload'], temp_api_key)
                    attempt = {
                        'model': model_id,
                        'path': check['path'],
                        'status_code': result.get('status_code'),
                        'ok': bool(result.get('ok')),
                        'elapsed_ms': result.get('elapsed_ms'),
                    }
                    body = result.get('body')
                    if body:
                        attempt['body'] = body[:260]
                    if result.get('error'):
                        attempt['error'] = result.get('error')
                    attempt['retry_after_seconds'] = _infer_retry_after_seconds(result)
                    attempts.append(attempt)
                    if result.get('ok') and int(result.get('status_code') or 0) == 200:
                        success = attempt
                        break
                if success:
                    break

            latest = success or (attempts[-1] if attempts else {})
            return {
                'ok': True,
                'auth_ref': auth_ref,
                'auth_name': item.get('name'),
                'available': bool(success),
                'working_model': success.get('model') if success else None,
                'working_path': success.get('path') if success else None,
                'status_code': latest.get('status_code'),
                'message': latest.get('body') or latest.get('error') or '',
                'elapsed_ms': latest.get('elapsed_ms'),
                'retry_after_seconds': latest.get('retry_after_seconds'),
                'failure_kind': _classify_failure(latest),
                'tested_at': int(time.time()),
                'attempts': attempts,
            }
        except Exception as e:
            return {
                'ok': False,
                'auth_ref': auth_ref,
                'available': False,
                'message': str(e),
                'retry_after_seconds': 120,
                'failure_kind': 'server',
                'tested_at': int(time.time()),
            }
        finally:
            if proc and process_alive(proc):
                kill_process(proc)


def _infer_retry_after_seconds(result: dict):
    status_code = int(result.get('status_code') or 0) if str(result.get('status_code') or '').isdigit() else 0
    body = str(result.get('body') or '')
    error = str(result.get('error') or '')
    text = f'{body}\n{error}'.lower()
    if result.get('ok') and status_code == 200:
        return 0
    if 'timed out' in text or 'timeout' in text:
        return 240
    if status_code == 429:
        return 900
    if status_code == 403:
        return 1800
    if status_code == 401:
        return 900
    if status_code >= 500:
        return 240
    if status_code >= 400:
        return 300
    return 90


def _classify_failure(result: dict):
    status_code = int(result.get('status_code') or 0) if str(result.get('status_code') or '').isdigit() else 0
    body = str(result.get('body') or '')
    error = str(result.get('error') or '')
    text = f'{body}\n{error}'.lower()
    if result.get('ok') and status_code == 200:
        return 'available'
    if 'winsock' in text or 'winerror 10106' in text or 'service provider could not be loaded or initialized' in text or 'socket stack is unavailable' in text:
        return 'infrastructure'
    if status_code == 429 or 'quota' in text or 'rate limit' in text or 'temporarily rate-limited' in text:
        return 'quota'
    if status_code == 403 or 'forbidden' in text or 'not authorized' in text or 'permission' in text:
        return 'forbidden'
    if status_code == 401 or 'unauthorized' in text or 'invalid api key' in text or 'user not found' in text:
        return 'auth'
    if 'timed out' in text or 'timeout' in text:
        return 'timeout'
    if status_code >= 500:
        return 'server'
    if status_code >= 400:
        return 'client'
    return 'unknown'


def _image_probe_model_id(model_id: str):
    model_value = str(model_id or '').strip()
    token = model_value.lower()
    if not model_value:
        return ''
    if token == 'gpt-image-2' or 'gpt-image' in token:
        return model_value
    for item in get_configured_provider_models():
        provider = str(item.get('lookup_provider') or item.get('provider') or '').strip().lower()
        for row in item.get('rows') or []:
            call_id = str(row.get('call_id') or row.get('alias') or row.get('name') or '').strip()
            if call_id != model_value:
                continue
            upstream_id = str(row.get('lookup_upstream_id') or row.get('upstream_id') or '').strip()
            runtime_upstream_id = str(row.get('upstream_id') or upstream_id).strip()
            if 'image' in derive_global_aggregate_aliases(provider, upstream_id, runtime_upstream_id):
                return model_value
    return ''


def _generic_probe_skip_reason(model_id: str):
    value = str(model_id or '').strip().lower()
    if not value:
        return None
    specialized_markers = (
        'embedding',
        'robotics',
        'tts',
        'transcribe',
        'transcription',
        'whisper',
        'prompt-guard',
        'safeguard',
    )
    if any(marker in value for marker in specialized_markers):
        return 'specialized model requires a non-chat probe'
    return None


def _video_probe_model_id(model_id: str):
    model_value = str(model_id or '').strip()
    if not model_value:
        return ''
    if _raw_media_model_kind(model_value) == 'video':
        return model_value
    resolved = _resolve_provider_media_model(model_value, desired_kind='video')
    if resolved:
        return str(resolved.get('call_id') or model_value).strip() or model_value
    return ''


def _candidate_checks_for_model(model_id: str):
    image_model = _image_probe_model_id(model_id)
    if image_model:
        return [{
            'path': '/v1/images/generations',
            'payload': {
                'model': image_model,
                'prompt': 'blue circle',
                'n': 1,
                'size': '256x256',
            },
        }]
    video_model = _video_probe_model_id(model_id)
    if video_model:
        return [{
            'path': '/v1/videos',
            'payload': {
                'model': video_model,
                'prompt': 'a cat walking',
                'seconds': '4',
            },
        }]
    common_messages = [{'role': 'user', 'content': 'Say OK only.'}]
    chat_check = {
        'path': '/v1/chat/completions',
        'payload': {
            'model': model_id,
            'messages': common_messages,
            'max_tokens': 16,
        },
    }
    # Use route-kind to decide test paths: api-key-mapped providers only need
    # the standard chat/completions probe; OAuth providers may also need messages
    # and responses probes because they can serve Anthropic / Responses APIs.
    route_kind = _provider_route_kind(_provider_for_model_id(model_id))
    if route_kind == 'api-key-mapping':
        return [chat_check]
    return [
        chat_check,
        {
            'path': '/v1/messages?beta=true',
            'payload': {
                'model': model_id,
                'messages': common_messages,
                'max_tokens': 16,
            },
        },
        {
            'path': '/v1/responses',
            'payload': {
                'model': model_id,
                'input': [{'role': 'user', 'content': 'Say OK only.'}],
            },
        },
        {
            'path': '/v1/responses',
            'payload': {
                'model': model_id,
                'input': [
                    {
                        'role': 'user',
                        'content': [{'type': 'input_text', 'text': 'Say OK only.'}],
                    }
                ],
            },
        },
        {
            'path': '/v1/responses',
            'payload': {
                'model': model_id,
                'input': 'Say OK only.',
            },
        },
    ]


def _normalize_model_ids(model_ids):
    unique_ids = []
    for model_id in model_ids or []:
        value = str(model_id or '').strip()
        if value and value not in unique_ids:
            unique_ids.append(value)
    return unique_ids


def _test_single_provider_model(model_id):
    with provider_model_test_lock:
        if _load_provider_model_test_state().get('cancel_requested'):
            return {
                'model': model_id,
                'available': False,
                'working_path': None,
                'status_code': None,
                'message': 'Cancelled by user.',
                'elapsed_ms': 0,
                'retry_after_seconds': 0,
                'failure_kind': 'client',
                'tested_at': int(time.time()),
                'attempts': [],
                'status': 'cancelled',
            }
    skip_reason = _generic_probe_skip_reason(model_id)
    if skip_reason:
        return {
            'model': model_id,
            'available': False,
            'working_path': None,
            'status_code': None,
            'message': skip_reason,
            'elapsed_ms': 0,
            'retry_after_seconds': 0,
            'failure_kind': 'specialized',
            'tested_at': int(time.time()),
            'attempts': [],
            'status': 'skipped',
        }

    attempts = []
    success = None
    last_error = None
    for check in _candidate_checks_for_model(model_id):
        with provider_model_test_lock:
            if _load_provider_model_test_state().get('cancel_requested'):
                return {
                    'model': model_id,
                    'available': False,
                    'working_path': None,
                    'status_code': None,
                    'message': 'Cancelled by user.',
                    'elapsed_ms': 0,
                    'retry_after_seconds': 0,
                    'failure_kind': 'client',
                    'tested_at': int(time.time()),
                    'attempts': attempts,
                    'status': 'cancelled',
                }
        result = _proxy_request(check['path'], check['payload'])
        attempt = {
            'path': check['path'],
            'status_code': result.get('status_code'),
            'ok': bool(result.get('ok')),
            'elapsed_ms': result.get('elapsed_ms'),
        }
        body = result.get('body')
        if body:
            attempt['body'] = body[:260]
        if result.get('error'):
            attempt['error'] = result.get('error')
        attempt['retry_after_seconds'] = _infer_retry_after_seconds(result)
        attempts.append(attempt)
        if result.get('ok') and int(result.get('status_code') or 0) == 200:
            success = {
                'path': check['path'],
                'status_code': result.get('status_code'),
                'body': body[:260] if body else '',
                'elapsed_ms': result.get('elapsed_ms'),
                'retry_after_seconds': 0,
            }
            break
        last_error = attempt

    latest = success or last_error or {}
    return {
        'model': model_id,
        'available': bool(success),
        'working_path': success.get('path') if success else None,
        'status_code': latest.get('status_code'),
        'message': latest.get('body') or latest.get('error') or '',
        'elapsed_ms': latest.get('elapsed_ms'),
        'retry_after_seconds': latest.get('retry_after_seconds'),
        'failure_kind': _classify_failure(latest),
        'tested_at': int(time.time()),
        'attempts': attempts,
    }


def test_provider_models(model_ids):
    unique_ids = _normalize_model_ids(model_ids)

    if not unique_ids:
        return {'ok': False, 'message': 'No model ids provided.', 'items': []}

    max_parallel = _provider_test_parallelism()
    result_map = {}
    pending = list(unique_ids)
    while pending:
        batch, pending = _select_provider_test_batch(pending, max_parallel)
        if not batch:
            batch = [pending.pop(0)]
        max_workers = max(1, min(max_parallel, len(batch)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_test_single_provider_model, model_id): model_id for model_id in batch}
            for future in as_completed(futures):
                model_id = futures[future]
                try:
                    result_map[model_id] = future.result()
                except Exception as e:
                    result_map[model_id] = {
                        'model': model_id,
                        'available': False,
                        'working_path': None,
                        'status_code': None,
                        'message': str(e),
                        'elapsed_ms': None,
                        'retry_after_seconds': 120,
                        'failure_kind': 'client',
                        'tested_at': int(time.time()),
                        'attempts': [],
                    }
        if pending:
            time.sleep(PROVIDER_MODEL_TEST_BATCH_PAUSE_SECONDS)
    items = [result_map.get(model_id) for model_id in unique_ids if result_map.get(model_id)]
    with provider_model_test_lock:
        state = _load_provider_model_test_state()
        results = state.setdefault('results', {})
        for item in items:
            model_id = str((item or {}).get('model') or '').strip()
            if not model_id:
                continue
            results[model_id] = item
            _record_provider_model_test_count(state, item)
        _save_provider_model_test_state()
    return {'ok': True, 'items': items}


def _image_result_summary(body: str):
    try:
        payload = json.loads(body or '{}')
    except Exception:
        return {'has_image': False, 'kind': '', 'preview': ''}

    def walk(value):
        if isinstance(value, dict):
            for key in ('b64_json', 'url', 'result', 'image_url'):
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    text = item.strip()
                    if key in ('b64_json', 'result') and len(text) > 80:
                        text = f'{text[:80]}...'
                    return {'has_image': True, 'kind': key, 'preview': text}
            for child in value.values():
                found = walk(child)
                if found.get('has_image'):
                    return found
        if isinstance(value, list):
            for child in value:
                found = walk(child)
                if found.get('has_image'):
                    return found
        return {'has_image': False, 'kind': '', 'preview': ''}

    return walk(payload)


def _test_single_image_model(model_id):
    model = str(model_id or '').strip()
    request_model = _image_probe_model_id(model)

    if request_model:
        mode = 'images'
        payload = {
            'model': request_model,
            'prompt': 'blue circle',
            'n': 1,
            'size': '256x256',
        }
        result = _proxy_request('/v1/images/generations', payload, timeout=90)
    else:
        mode = 'unsupported'
        result = {
            'ok': False,
            'status_code': 400,
            'body': 'Model is not in image test allowlist. Use gpt-image aliases or models detected by provider image rules.',
            'elapsed_ms': 0,
        }

    body = result.get('body') or ''
    summary = _image_result_summary(body) if result.get('ok') else {'has_image': False, 'kind': '', 'preview': ''}
    available = bool(result.get('ok')) and int(result.get('status_code') or 0) == 200 and bool(summary.get('has_image'))
    return {
        'model': model_id,
        'mode': mode,
        'available': available,
        'status_code': result.get('status_code'),
        'message': 'Image returned.' if available else (body[:320] if body else result.get('error') or 'No image data returned.'),
        'elapsed_ms': result.get('elapsed_ms'),
        'failure_kind': 'available' if available else _classify_failure(result),
        'image_kind': summary.get('kind') or '',
        'image_preview': summary.get('preview') or '',
        'tested_at': int(time.time()),
    }


def test_image_models(model_ids):
    unique_ids = _normalize_model_ids(model_ids)[:20]
    if not unique_ids:
        return {'ok': False, 'message': 'No model ids provided.', 'items': []}

    result_map = {}
    max_workers = max(1, min(2, len(unique_ids)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_test_single_image_model, model_id): model_id for model_id in unique_ids}
        for future in as_completed(futures):
            model_id = futures[future]
            try:
                result_map[model_id] = future.result()
            except Exception as e:
                result_map[model_id] = {
                    'model': model_id,
                    'available': False,
                    'status_code': None,
                    'message': str(e),
                    'elapsed_ms': None,
                    'failure_kind': 'client',
                    'image_kind': '',
                    'image_preview': '',
                    'tested_at': int(time.time()),
                }
    return {'ok': True, 'items': [result_map[model_id] for model_id in unique_ids if model_id in result_map]}


def _provider_model_test_worker():
    global provider_model_test_worker_running
    while True:
        with provider_model_test_lock:
            state = _load_provider_model_test_state()
            if state.get('cancel_requested'):
                state['queue'] = []
                state['running'] = []
                state['cancel_requested'] = False
                provider_model_test_worker_running = False
                _save_provider_model_test_state()
                return
            queue = state.get('queue', [])
            if not queue:
                provider_model_test_worker_running = False
                _save_provider_model_test_state()
                return
            max_parallel = _provider_test_parallelism()
            batch, remaining_queue = _select_provider_test_batch(queue, max_parallel)
            state['queue'] = remaining_queue
            running = state.get('running', [])
            for model_id in batch:
                if model_id not in running:
                    running.append(model_id)
            state['running'] = running
            _save_provider_model_test_state()
        if not batch:
            continue

        max_parallel = _provider_test_parallelism()
        max_workers = max(1, min(max_parallel, len(batch)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_test_single_provider_model, model_id): model_id for model_id in batch}
            for future in as_completed(futures):
                model_id = futures[future]
                try:
                    item = future.result()
                except Exception as e:
                    item = {
                        'model': model_id,
                        'available': False,
                        'working_path': None,
                        'status_code': None,
                        'message': str(e),
                        'elapsed_ms': None,
                        'retry_after_seconds': 120,
                        'failure_kind': 'client',
                        'tested_at': int(time.time()),
                        'attempts': [],
                    }
                with provider_model_test_lock:
                    state = _load_provider_model_test_state()
                    if state.get('cancel_requested'):
                        state['queue'] = []
                        state['running'] = []
                        state['cancel_requested'] = False
                        provider_model_test_worker_running = False
                        _save_provider_model_test_state()
                        return
                    state.setdefault('results', {})[model_id] = item
                    _record_provider_model_test_count(state, item)
                    state['running'] = [value for value in state.get('running', []) if value != model_id]
                    _save_provider_model_test_state()
        with provider_model_test_lock:
            state = _load_provider_model_test_state()
            if state.get('cancel_requested'):
                state['queue'] = []
                state['running'] = []
                state['cancel_requested'] = False
                provider_model_test_worker_running = False
                _save_provider_model_test_state()
                return
            has_more_work = bool(state.get('queue'))
        if has_more_work:
            time.sleep(PROVIDER_MODEL_TEST_BATCH_PAUSE_SECONDS)


def queue_provider_model_tests(model_ids):
    global provider_model_test_worker_running
    unique_ids = _normalize_model_ids(model_ids)
    if not unique_ids:
        return {'ok': False, 'message': 'No model ids provided.', 'queued': [], 'running': []}

    with provider_model_test_lock:
        state = _load_provider_model_test_state()
        queue = list(state.get('queue', []))
        running = list(state.get('running', []))
        results = state.setdefault('results', {})
        queued = []
        for model_id in unique_ids:
            queue.append(model_id)
            queued.append(model_id)
        state['queue'] = queue
        for model_id in unique_ids:
            results[model_id] = {
                'model': model_id,
                'available': False,
                'tested_at': int(time.time()),
                'status': 'testing',
                'message': '',
                'working_path': None,
                'status_code': None,
                'elapsed_ms': None,
                'retry_after_seconds': 0,
                'failure_kind': None,
                'attempts': [],
            }
        _save_provider_model_test_state()

        if not provider_model_test_worker_running and (queue or running):
            provider_model_test_worker_running = True
            thread = threading.Thread(target=_provider_model_test_worker, daemon=True)
            thread.start()

        return {
            'ok': True,
            'message': f'Queued {len(queued)} model checks (parallel max {_provider_test_parallelism()}, per-provider max {_provider_test_max_per_provider()}).',
            'queued': queued,
            'running': list(state.get('running', [])),
        }


def clear_provider_model_test_state(model_ids=None):
    ids = _normalize_model_ids(model_ids)
    with provider_model_test_lock:
        state = _load_provider_model_test_state()
        if not ids:
            state['results'] = {}
            state['test_counts'] = {}
            state['queue'] = []
            state['running'] = []
        else:
            for model_id in ids:
                state.get('results', {}).pop(model_id, None)
                state.get('test_counts', {}).pop(model_id, None)
            state['queue'] = [value for value in state.get('queue', []) if value not in ids]
            state['running'] = [value for value in state.get('running', []) if value not in ids]
        _save_provider_model_test_state()
        return {
            'ok': True,
            'message': 'Cleared provider model test results.',
            'results': state.get('results', {}),
            'test_counts': state.get('test_counts', {}),
            'running': state.get('running', []),
            'queue': state.get('queue', []),
        }


def stop_provider_model_tests():
    global provider_model_test_worker_running
    with provider_model_test_lock:
        state = _load_provider_model_test_state()
        state['queue'] = []
        state['running'] = []
        state['cancel_requested'] = True
        _save_provider_model_test_state()
        return {
            'ok': True,
            'message': 'Stopped provider model tests.',
            'results': state.get('results', {}),
            'test_counts': state.get('test_counts', {}),
            'running': [],
            'queue': [],
        }
