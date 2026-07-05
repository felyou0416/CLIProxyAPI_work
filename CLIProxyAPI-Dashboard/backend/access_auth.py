import hashlib
import hmac
import json
import secrets
import time
import threading
from pathlib import Path
from backend.paths import RUNTIME_DIR

_ACCESS_PASSWORD_FILE = RUNTIME_DIR / 'access_password.json'
_ACTIVE_TOKENS_FILE = RUNTIME_DIR / 'access_tokens.json'

_lock = threading.Lock()
_token_store = {}
_token_loaded = False


def _hash_password(password: str, salt: str = None) -> dict:
    if salt is None:
        salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    return {'salt': salt, 'hash': pw_hash, 'iterations': 100000}


def password_is_set() -> bool:
    return _ACCESS_PASSWORD_FILE.exists()


def _load_password_data() -> dict:
    if not _ACCESS_PASSWORD_FILE.exists():
        return {}
    try:
        return json.loads(_ACCESS_PASSWORD_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def verify_password(password: str) -> bool:
    data = _load_password_data()
    if not data:
        return False
    salt = data.get('salt', '')
    expected_hash = data.get('hash', '')
    iterations = int(data.get('iterations', 100000))
    pw_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations).hex()
    return hmac.compare_digest(pw_hash, expected_hash)


def set_access_password(new_password: str) -> dict:
    if not new_password:
        if _ACCESS_PASSWORD_FILE.exists():
            _ACCESS_PASSWORD_FILE.unlink()
        _clear_all_tokens()
        return {'ok': True, 'password_set': False}
    hashed = _hash_password(new_password)
    _ACCESS_PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _ACCESS_PASSWORD_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(hashed, indent=2), encoding='utf-8')
    tmp.replace(_ACCESS_PASSWORD_FILE)
    _clear_all_tokens()
    return {'ok': True, 'password_set': True}


def _load_tokens():
    global _token_store, _token_loaded
    if _token_loaded:
        return
    _token_store = {}
    if _ACTIVE_TOKENS_FILE.exists():
        try:
            data = json.loads(_ACTIVE_TOKENS_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                _token_store = data
        except Exception:
            pass
    _token_loaded = True


def _save_tokens():
    _ACTIVE_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _ACTIVE_TOKENS_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(_token_store, indent=2), encoding='utf-8')
    tmp.replace(_ACTIVE_TOKENS_FILE)


def create_token() -> str:
    _lock.acquire()
    try:
        _load_tokens()
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        _token_store[token] = {'created_at': now, 'expires_at': now + 30 * 24 * 3600}
        _prune_expired_tokens(now)
        _save_tokens()
        return token
    finally:
        _lock.release()


def validate_token(token: str) -> bool:
    if not token:
        return False
    _lock.acquire()
    try:
        _load_tokens()
        now = int(time.time())
        info = _token_store.get(token)
        if not info:
            return False
        if info.get('expires_at', 0) < now:
            del _token_store[token]
            _save_tokens()
            return False
        info['expires_at'] = now + 30 * 24 * 3600
        _save_tokens()
        return True
    finally:
        _lock.release()


def revoke_token(token: str) -> bool:
    _lock.acquire()
    try:
        _load_tokens()
        if token in _token_store:
            del _token_store[token]
            _save_tokens()
            return True
        return False
    finally:
        _lock.release()


def _clear_all_tokens():
    _lock.acquire()
    try:
        _token_store = {}
        _token_loaded = True
        if _ACTIVE_TOKENS_FILE.exists():
            _ACTIVE_TOKENS_FILE.unlink()
    finally:
        _lock.release()


def _prune_expired_tokens(now: int):
    expired = [t for t, info in _token_store.items() if info.get('expires_at', 0) < now]
    for t in expired:
        del _token_store[t]


def auth_required() -> bool:
    return password_is_set()


def extract_token_from_handler(handler) -> str:
    auth_header = handler.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:].strip()
    cookie = handler.headers.get('Cookie', '')
    for part in cookie.split(';'):
        part = part.strip()
        if part.startswith('access_token='):
            return part[13:].strip()
    return ''
