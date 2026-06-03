import json
import secrets
import threading
from backend.paths import STATE_FILE, RUNTIME_CONFIG, POOL_AUTH_DIR, ROOT_DIR

_state_lock = threading.Lock()


def generate_exposure_api_key():
    return 'cliproxyapi-' + secrets.token_urlsafe(24)


def default_route_strategy():
    return {
        'enabled': True,
        'aggregate_only': True,
        'probe_parallelism': 12,
        'cooldown_default_seconds': 300,
        'cooldown_forbidden_seconds': 1800,
        'cooldown_quota_seconds': 900,
        'cooldown_auth_seconds': 900,
        'cooldown_timeout_seconds': 240,
        'cooldown_server_seconds': 240,
        'cooldown_client_seconds': 300,
    }


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in ('1', 'true', 'yes', 'on'):
            return True
        if token in ('0', 'false', 'no', 'off', ''):
            return False
    return bool(value)


def _bounded_int(value, default, lower, upper):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(upper, parsed))


def normalize_route_strategy(value):
    defaults = default_route_strategy()
    raw = value if isinstance(value, dict) else {}
    merged = dict(defaults)
    merged.update({k: raw.get(k) for k in defaults.keys() if k in raw})

    merged['enabled'] = _as_bool(merged.get('enabled'))
    merged['aggregate_only'] = _as_bool(merged.get('aggregate_only'))
    merged['probe_parallelism'] = _bounded_int(merged.get('probe_parallelism'), defaults['probe_parallelism'], 1, 24)
    for key in (
        'cooldown_default_seconds',
        'cooldown_forbidden_seconds',
        'cooldown_quota_seconds',
        'cooldown_auth_seconds',
        'cooldown_timeout_seconds',
        'cooldown_server_seconds',
        'cooldown_client_seconds',
    ):
        merged[key] = _bounded_int(merged.get(key), defaults[key], 0, 86400)
    return merged


def get_proxy_bind_host(state=None):
    return '0.0.0.0' if (state or {}).get('exposure_enabled') else '127.0.0.1'


def get_proxy_api_key(state=None):
    current = state or {}
    if current.get('exposure_enabled'):
        return current.get('exposure_api_key') or generate_exposure_api_key()
    return 'cliproxyapi'


def default_state():
    return {
        'selected_auth': None,
        'selected_auth_ref': None,
        'selected_auths': [],
        'selected_auth_refs': [],
        'applied_auth': None,
        'applied_auth_ref': None,
        'applied_auths': [],
        'applied_auth_refs': [],
        'last_runtime_config': _portable_path(RUNTIME_CONFIG),
        'last_active_auth_dir': _portable_path(POOL_AUTH_DIR),
        'exposure_enabled': False,
        'exposure_api_key': generate_exposure_api_key(),
        'route_strategy': default_route_strategy(),
        'notes': 'Select an auth file, then start RelayX for CC-switch / Claude.',
        'disable_cooling': False,
        'auth_auto_refresh_workers': 16,
        'disable_image_generation': 'off',
        'session_affinity_enabled': False,
        'session_affinity_ttl': '1h',
        'ws_auth': False,
        'local_model': False,
        'commercial_mode': False,
    }


def _portable_path(path):
    try:
        return path.relative_to(ROOT_DIR).as_posix()
    except Exception:
        return path.as_posix()


def _normalize_runtime_paths(state: dict):
    state['last_runtime_config'] = _portable_path(RUNTIME_CONFIG)
    state['last_active_auth_dir'] = _portable_path(POOL_AUTH_DIR)
    return state


def load_state():
    if not STATE_FILE.exists():
        return default_state()
    try:
        with _state_lock:
            data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        merged = default_state()
        merged.update(data)
        if not isinstance(merged.get('selected_auth_refs'), list):
            merged['selected_auth_refs'] = [merged['selected_auth_ref']] if merged.get('selected_auth_ref') else []
        if not isinstance(merged.get('selected_auths'), list):
            merged['selected_auths'] = [merged['selected_auth']] if merged.get('selected_auth') else []
        if not isinstance(merged.get('applied_auth_refs'), list):
            merged['applied_auth_refs'] = [merged['applied_auth_ref']] if merged.get('applied_auth_ref') else []
        if not isinstance(merged.get('applied_auths'), list):
            merged['applied_auths'] = [merged['applied_auth']] if merged.get('applied_auth') else []
        if not merged.get('exposure_api_key'):
            merged['exposure_api_key'] = generate_exposure_api_key()
        merged['route_strategy'] = normalize_route_strategy(merged.get('route_strategy'))
        return _normalize_runtime_paths(merged)
    except Exception:
        return default_state()


def save_state(state):
    state = _normalize_runtime_paths(dict(state or {}))
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    temp_path = STATE_FILE.with_suffix('.tmp')
    with _state_lock:
        temp_path.write_text(payload, encoding='utf-8')
        temp_path.replace(STATE_FILE)
