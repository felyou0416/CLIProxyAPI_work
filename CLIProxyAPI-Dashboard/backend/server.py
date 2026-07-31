import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from backend.paths import CLI_EXE, BASE_CONFIG, SOURCE_AUTH_DIR, RUNTIME_DIR, PROXY_ROOT, DASHBOARD_ROOT, STORAGE_DIR, RUNTIME_VARIANT
from backend.processes import shutdown_all, start_proxy
from backend.routes.get_routes import handle_get
from backend.routes.post_routes import handle_post
from backend.routes.helpers import send_json
from backend.request_metrics import start_observability_refresh_thread
from backend.auth import start_auth_pool_sync_thread
from backend.runtime_env import dashboard_auto_start_enabled
from backend.access_auth import auth_required, validate_token, extract_token_from_handler

MAX_REQUEST_BYTES = 2 * 1024 * 1024
DEFAULT_DASHBOARD_HOST = '127.0.0.1'

_PUBLIC_PATHS = {
    '/api/auth/login',
    '/api/auth/check',
    '/api/auth/set-password',
}


# Static UI assets stay public so the shell can boot without 401 thrash / half-loaded scripts.
# API routes remain protected by auth_required() + token checks below.
_PUBLIC_STATIC_PREFIXES = (
    '/js/',
    '/css/',
    '/sections/',
    '/generated/',
)

_PUBLIC_STATIC_FILES = {
    '/',
    '/index.html',
    '/dashboard.css',
    '/favicon.ico',
    '/favicon.svg',
    '/favicon.png',
}


def _is_public_path(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    if path in _PUBLIC_STATIC_FILES:
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_STATIC_PREFIXES)


def _check_auth(handler, parsed) -> bool:
    if not auth_required():
        return True
    if _is_public_path(parsed.path):
        return True
    token = extract_token_from_handler(handler)
    if token and validate_token(token):
        return True
    send_json(handler, {'ok': False, 'message': 'Authentication required', 'auth_required': True}, status=401)
    return False


def _flatten_form_data(raw: str):
    parsed = parse_qs(raw, keep_blank_values=True)
    result = {}
    for key, values in parsed.items():
        if not values:
            result[key] = ''
        elif len(values) == 1:
            result[key] = values[0]
        else:
            result[key] = values
    return result


def _read_request_data(handler):
    try:
        length = int(handler.headers.get('Content-Length', '0') or 0)
    except (TypeError, ValueError):
        raise ValueError('Invalid Content-Length header.')
    if length < 0:
        raise ValueError('Invalid Content-Length header.')
    if length > MAX_REQUEST_BYTES:
        raise OverflowError(f'Request body too large. Limit is {MAX_REQUEST_BYTES} bytes.')
    raw = handler.rfile.read(length).decode('utf-8') if length else '{}'
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return _flatten_form_data(raw)


_SENSITIVE_PATHS = {
    # Terminals
    '/api/terminals',
    '/api/terminals/open',
    '/api/terminals/open-desktop',
    '/api/terminals/close',
    '/api/terminals/input',
    '/api/terminals/resize',
    '/api/terminals/output',

    # Port Bindings & Firewall
    '/api/port-bindings',
    '/api/port-bindings/enable',
    '/api/port-bindings/remove',
    '/api/ip-helper',
    '/api/firewall-access',
    '/api/firewall-access/allow',
    '/api/firewall-access/remove',

    # Network access
    '/api/network-access',
    '/api/network-access/firewall/allow',
}


def _check_sensitive_auth(handler, parsed) -> bool:
    if parsed.path not in _SENSITIVE_PATHS:
        return True
    from backend.state import load_state
    import hmac
    state = load_state()
    expected_key = state.get('sensitive_auth_key', '').strip()
    if not expected_key:
        return True
    
    # Extract client key from header
    client_key = handler.headers.get('X-Sensitive-Auth-Key', '').strip()
    if not client_key:
        # Check query param fallback
        params = parse_qs(parsed.query)
        client_key = (params.get('sensitive_key') or [''])[0].strip()

    if client_key and hmac.compare_digest(client_key, expected_key):
        return True

    send_json(handler, {
        'ok': False,
        'message': 'Sensitive operation authorization required',
        'sensitive_auth_required': True
    }, status=403)
    return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if not _check_auth(self, parsed):
            return
        if not _check_sensitive_auth(self, parsed):
            return
        if handle_get(self, parsed):
            return
        send_json(self, {'ok': False, 'message': 'Not found'}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not _check_auth(self, parsed):
            return
        if not _check_sensitive_auth(self, parsed):
            return
        try:
            data = _read_request_data(self)
        except OverflowError as exc:
            send_json(self, {'ok': False, 'message': str(exc)}, status=413)
            return
        except ValueError as exc:
            send_json(self, {'ok': False, 'message': str(exc)}, status=400)
            return
        if handle_post(self, parsed, data):
            return
        send_json(self, {'ok': False, 'message': 'Not found'}, status=404)


def _auto_start_proxy_async():
    """Start RelayX after HTTP is already accepting connections.

    Cold boot used to block serve_forever() on start_proxy(), so health checks
    timed out and the panel looked like it failed to launch.
    """
    try:
        result = start_proxy()
        print(f'Auto start RelayX: {result.get("message", "")}')
    except Exception as exc:
        print(f'Auto start RelayX failed: {exc}')


def main():
    host = (os.environ.get('CLIPROXYAPI_DASHBOARD_HOST', DEFAULT_DASHBOARD_HOST) or DEFAULT_DASHBOARD_HOST).strip() or DEFAULT_DASHBOARD_HOST
    port = int((os.environ.get('CLIPROXYAPI_DASHBOARD_PORT', '8765') or '8765').strip() or '8765')
    server = ThreadingHTTPServer((host, port), Handler)
    display_host = '127.0.0.1' if host in ('0.0.0.0', '') else host
    print(f'Dashboard running at http://{display_host}:{port} (bind: {host})')
    print(f'Dashboard root: {DASHBOARD_ROOT}')
    print(f'Proxy root: {PROXY_ROOT}')
    print(f'Storage dir: {STORAGE_DIR}')
    print(f'Runtime variant: {RUNTIME_VARIANT}')
    print(f'CLI executable: {CLI_EXE}')
    print(f'Base config: {BASE_CONFIG}')
    print(f'Source auth dir: {SOURCE_AUTH_DIR}')
    print(f'Runtime dir: {RUNTIME_DIR}')
    # Accept HTTP immediately so launcher health checks and the UI do not wait
    # on RelayX / MediaProxy startup (which can take tens of seconds at boot).
    start_observability_refresh_thread()
    print('Observability cache refresher started')
    start_auth_pool_sync_thread()
    print('Auth pool hot-sync started')
    if dashboard_auto_start_enabled():
        print('Auto start RelayX scheduled in background')
        threading.Thread(target=_auto_start_proxy_async, name='auto-start-proxy', daemon=True).start()
    else:
        print('Auto start RelayX skipped because CLIPROXYAPI_AUTO_START is disabled.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        shutdown_all()
