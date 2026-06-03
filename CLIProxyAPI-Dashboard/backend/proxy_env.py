import os
import threading
from pathlib import Path
from backend.paths import RUNTIME_DIR

PROXY_ENV_FILE = RUNTIME_DIR / '.env.proxy'

_env_lock = threading.Lock()

SENSITIVE_KEYS = {
    'PGSTORE_DSN', 'PGSTORE_SCHEMA',
    'GITSTORE_GIT_URL', 'GITSTORE_GIT_USERNAME', 'GITSTORE_GIT_TOKEN', 'GITSTORE_GIT_BRANCH',
    'OBJECTSTORE_ENDPOINT', 'OBJECTSTORE_ACCESS_KEY', 'OBJECTSTORE_SECRET_KEY', 'OBJECTSTORE_BUCKET',
    'HOME_JWT',
}

STORAGE_ENV_VARS = {
    'PGSTORE_DSN', 'PGSTORE_SCHEMA', 'PGSTORE_LOCAL_PATH',
    'GITSTORE_GIT_URL', 'GITSTORE_GIT_USERNAME', 'GITSTORE_GIT_TOKEN',
    'GITSTORE_GIT_BRANCH', 'GITSTORE_LOCAL_PATH',
    'OBJECTSTORE_ENDPOINT', 'OBJECTSTORE_ACCESS_KEY', 'OBJECTSTORE_SECRET_KEY',
    'OBJECTSTORE_BUCKET', 'OBJECTSTORE_LOCAL_PATH',
}


def load_proxy_env():
    if not PROXY_ENV_FILE.exists():
        return {}
    with _env_lock:
        result = {}
        for line in PROXY_ENV_FILE.read_text(encoding='utf-8').splitlines():
            text = line.strip()
            if not text or text.startswith('#') or '=' not in text:
                continue
            key, value = text.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                result[key] = value
        return result


def save_proxy_env(updates: dict):
    current = load_proxy_env()
    for key, value in (updates or {}).items():
        key = str(key).strip()
        if not key:
            continue
        if value is None or str(value).strip() == '':
            current.pop(key, None)
        else:
            current[key] = str(value).strip()
    PROXY_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{k}={v}' for k, v in sorted(current.items()) if k and v]
    with _env_lock:
        PROXY_ENV_FILE.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')


def build_proxy_env_dict(state: dict) -> dict:
    extra_env = {}
    stored = load_proxy_env()
    for key in STORAGE_ENV_VARS:
        val = stored.get(key, '')
        if val:
            extra_env[key] = val
    home_jwt = stored.get('HOME_JWT', '')
    if home_jwt:
        extra_env['HOME_JWT'] = home_jwt
    return extra_env


def get_proxy_env_path() -> Path:
    return PROXY_ENV_FILE


def mask_sensitive(data: dict) -> dict:
    result = {}
    for key, value in (data or {}).items():
        if key in SENSITIVE_KEYS and value:
            result[key] = '***'
            result[f'{key}_set'] = True
        else:
            result[key] = value
    return result
