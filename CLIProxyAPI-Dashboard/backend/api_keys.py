"""
Virtual API Key management for multi-user access.

Allows the admin to create, edit, delete, and manage virtual API keys
that can be distributed to other users. Each key can have:
- Token quota limits
- Request count limits
- Rate limits (requests per minute)
- Model access control (whitelist)
- Expiration dates
"""

import json
import secrets
import threading
import time
from pathlib import Path

from backend.paths import STORAGE_DIR


API_KEYS_FILE = STORAGE_DIR / 'config' / 'virtual_api_keys.json'
API_KEYS_USAGE_FILE = STORAGE_DIR / 'cache' / 'api_keys_usage.json'

_KEYS_LOCK = threading.Lock()
_USAGE_LOCK = threading.Lock()
_MASKED_KEY_CACHE = {}  # masked_value -> full_key_value


def _generate_key() -> str:
    """Generate a unique virtual API key with recognizable prefix."""
    return 'sk-cliproxy-' + secrets.token_urlsafe(32)


def _load_keys() -> list[dict]:
    """Load all virtual API keys from disk."""
    if not API_KEYS_FILE.exists():
        return []
    try:
        payload = json.loads(API_KEYS_FILE.read_text(encoding='utf-8'))
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            return payload.get('keys') or []
    except Exception:
        return []
    return []


def _save_keys(keys: list[dict]) -> None:
    """Persist virtual API keys to disk."""
    API_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    API_KEYS_FILE.write_text(
        json.dumps({'keys': keys}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    global _MASKED_KEY_CACHE
    _MASKED_KEY_CACHE = {}  # Invalidate cache


def _load_usage() -> dict:
    """Load usage tracking data."""
    if not API_KEYS_USAGE_FILE.exists():
        return {}
    try:
        payload = json.loads(API_KEYS_USAGE_FILE.read_text(encoding='utf-8'))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_usage(usage: dict) -> None:
    """Persist usage tracking data."""
    API_KEYS_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    API_KEYS_USAGE_FILE.write_text(
        json.dumps(usage, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def list_api_keys() -> list[dict]:
    """List all virtual API keys with their current usage stats."""
    with _KEYS_LOCK:
        keys = _load_keys()
    with _USAGE_LOCK:
        usage = _load_usage()

    now = int(time.time())
    result = []
    for key_entry in keys:
        key_id = str(key_entry.get('id') or '').strip()
        if not key_id:
            continue
        key_usage = usage.get(key_id) or {}
        masked_key = _mask_key(str(key_entry.get('key') or ''))
        expires_at = int(key_entry.get('expires_at') or 0)
        is_expired = bool(expires_at and expires_at < now)
        is_enabled = bool(key_entry.get('enabled', True)) and not is_expired

        result.append({
            'id': key_id,
            'key_masked': masked_key,
            'name': str(key_entry.get('name') or '').strip(),
            'note': str(key_entry.get('note') or '').strip(),
            'enabled': is_enabled,
            'expired': is_expired,
            'created_at': int(key_entry.get('created_at') or 0),
            'expires_at': expires_at,
            'allowed_models': key_entry.get('allowed_models') or [],
            'rate_limit_rpm': int(key_entry.get('rate_limit_rpm') or 0),
            'max_tokens': int(key_entry.get('max_tokens') or 0),
            'max_requests': int(key_entry.get('max_requests') or 0),
            'used_tokens': int(key_usage.get('used_tokens') or 0),
            'used_requests': int(key_usage.get('used_requests') or 0),
            'last_used_at': int(key_usage.get('last_used_at') or 0),
        })

    result.sort(key=lambda item: (-int(item.get('created_at') or 0), item.get('name') or ''))
    return result


def _mask_key(key: str) -> str:
    """Mask a key for display, showing only prefix and last 4 chars."""
    if len(key) <= 16:
        return key[:8] + '...'
    return key[:14] + '...' + key[-4:]


def create_api_key(
    name: str,
    note: str = '',
    allowed_models: list[str] | None = None,
    rate_limit_rpm: int = 0,
    max_tokens: int = 0,
    max_requests: int = 0,
    expires_at: int = 0,
) -> dict:
    """Create a new virtual API key."""
    name = str(name or '').strip()
    if not name:
        raise ValueError('Key name is required.')

    key_value = _generate_key()
    key_id = secrets.token_hex(8)
    now = int(time.time())

    entry = {
        'id': key_id,
        'key': key_value,
        'name': name,
        'note': str(note or '').strip(),
        'enabled': True,
        'created_at': now,
        'expires_at': max(0, int(expires_at or 0)),
        'allowed_models': [str(m).strip() for m in (allowed_models or []) if str(m).strip()],
        'rate_limit_rpm': max(0, int(rate_limit_rpm or 0)),
        'max_tokens': max(0, int(max_tokens or 0)),
        'max_requests': max(0, int(max_requests or 0)),
    }

    with _KEYS_LOCK:
        keys = _load_keys()
        keys.append(entry)
        _save_keys(keys)

    return {
        'id': key_id,
        'key': key_value,  # Show full key only on creation
        'key_masked': _mask_key(key_value),
        'name': entry['name'],
        'created_at': now,
    }


def update_api_key(
    key_id: str,
    name: str | None = None,
    note: str | None = None,
    enabled: bool | None = None,
    allowed_models: list[str] | None = None,
    rate_limit_rpm: int | None = None,
    max_tokens: int | None = None,
    max_requests: int | None = None,
    expires_at: int | None = None,
) -> dict:
    """Update an existing virtual API key."""
    key_id = str(key_id or '').strip()
    if not key_id:
        raise ValueError('Key ID is required.')

    with _KEYS_LOCK:
        keys = _load_keys()
        entry = next((k for k in keys if k.get('id') == key_id), None)
        if not entry:
            raise ValueError(f'Key not found: {key_id}')

        if name is not None:
            entry['name'] = str(name).strip()
        if note is not None:
            entry['note'] = str(note).strip()
        if enabled is not None:
            entry['enabled'] = bool(enabled)
        if allowed_models is not None:
            entry['allowed_models'] = [str(m).strip() for m in allowed_models if str(m).strip()]
        if rate_limit_rpm is not None:
            entry['rate_limit_rpm'] = max(0, int(rate_limit_rpm))
        if max_tokens is not None:
            entry['max_tokens'] = max(0, int(max_tokens))
        if max_requests is not None:
            entry['max_requests'] = max(0, int(max_requests))
        if expires_at is not None:
            entry['expires_at'] = max(0, int(expires_at))

        _save_keys(keys)

    return {'id': key_id, 'updated': True}


def delete_api_key(key_id: str) -> dict:
    """Delete a virtual API key."""
    key_id = str(key_id or '').strip()
    if not key_id:
        raise ValueError('Key ID is required.')

    with _KEYS_LOCK:
        keys = _load_keys()
        before = len(keys)
        keys = [k for k in keys if k.get('id') != key_id]
        if len(keys) == before:
            raise ValueError(f'Key not found: {key_id}')
        _save_keys(keys)

    # Clean up usage data
    with _USAGE_LOCK:
        usage = _load_usage()
        usage.pop(key_id, None)
        _save_usage(usage)

    return {'id': key_id, 'deleted': True}


def reset_api_key_usage(key_id: str) -> dict:
    """Reset usage counters for a virtual API key."""
    key_id = str(key_id or '').strip()
    if not key_id:
        raise ValueError('Key ID is required.')

    with _USAGE_LOCK:
        usage = _load_usage()
        usage[key_id] = {
            'used_tokens': 0,
            'used_requests': 0,
            'last_used_at': 0,
            'reset_at': int(time.time()),
        }
        _save_usage(usage)

    return {'id': key_id, 'reset': True}


def record_api_key_usage(key_value: str, tokens: int = 0) -> None:
    """Record usage for a virtual API key (called after successful request)."""
    key_value = str(key_value or '').strip()
    if not key_value:
        return

    # Find the key ID by the raw key value
    with _KEYS_LOCK:
        keys = _load_keys()
        entry = next((k for k in keys if k.get('key') == key_value), None)
        if not entry:
            return
        key_id = str(entry.get('id') or '').strip()

    if not key_id:
        return

    with _USAGE_LOCK:
        usage = _load_usage()
        key_usage = usage.get(key_id) or {}
        key_usage['used_tokens'] = int(key_usage.get('used_tokens') or 0) + max(0, int(tokens or 0))
        key_usage['used_requests'] = int(key_usage.get('used_requests') or 0) + 1
        key_usage['last_used_at'] = int(time.time())
        usage[key_id] = key_usage
        _save_usage(usage)


def get_all_active_key_values() -> list[str]:
    """Get all active (enabled, non-expired) virtual API key values for config injection."""
    now = int(time.time())
    with _KEYS_LOCK:
        keys = _load_keys()
    values = []
    for entry in keys:
        if not entry.get('enabled', True):
            continue
        expires_at = int(entry.get('expires_at') or 0)
        if expires_at and expires_at < now:
            continue
        key_value = str(entry.get('key') or '').strip()
        if key_value:
            values.append(key_value)
    return values


def reveal_api_key(key_id: str) -> dict:
    """Reveal the full API key value (admin only)."""
    key_id = str(key_id or '').strip()
    if not key_id:
        raise ValueError('Key ID is required.')

    with _KEYS_LOCK:
        keys = _load_keys()
        entry = next((k for k in keys if k.get('id') == key_id), None)
        if not entry:
            raise ValueError(f'Key not found: {key_id}')

    return {
        'id': key_id,
        'key': str(entry.get('key') or ''),
    }


def find_key_by_masked_value(masked_value: str) -> str | None:
    """
    Try to find a virtual API key that matches the masked value from logs.
    Masked value format example: 'sk-c...xxxx' or 'sk-cliproxy-le...K1mk'
    """
    masked_value = str(masked_value or '').strip()
    if not masked_value or '...' not in masked_value:
        return None

    global _MASKED_KEY_CACHE
    if masked_value in _MASKED_KEY_CACHE:
        return _MASKED_KEY_CACHE[masked_value]

    prefix, suffix = masked_value.split('...', 1)
    
    with _KEYS_LOCK:
        keys = _load_keys()
    
    found_key = None
    for entry in keys:
        key_val = str(entry.get('key') or '')
        if key_val.startswith(prefix) and key_val.endswith(suffix):
            found_key = key_val
            break
            
    if found_key:
        _MASKED_KEY_CACHE[masked_value] = found_key
    return found_key
