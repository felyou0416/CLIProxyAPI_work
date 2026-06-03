import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from backend.paths import CLI_EXE, BASE_CONFIG, SOURCE_AUTH_DIR, RUNTIME_DIR, PROXY_ROOT, DASHBOARD_ROOT, STORAGE_DIR, RUNTIME_VARIANT
from backend.processes import shutdown_all, start_proxy
from backend.routes.get_routes import handle_get
from backend.routes.post_routes import handle_post
from backend.routes.helpers import send_json
from backend.request_metrics import start_observability_refresh_thread
from backend.runtime_env import dashboard_auto_start_enabled

MAX_REQUEST_BYTES = 2 * 1024 * 1024
DEFAULT_DASHBOARD_HOST = '127.0.0.1'


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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if handle_get(self, parsed):
            return
        send_json(self, {'ok': False, 'message': 'Not found'}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
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
    if dashboard_auto_start_enabled():
        try:
            result = start_proxy()
            print(f'Auto start RelayX: {result.get("message", "")}')
        except Exception as exc:
            print(f'Auto start RelayX failed: {exc}')
    else:
        print('Auto start RelayX skipped because CLIPROXYAPI_AUTO_START is disabled.')
    start_observability_refresh_thread()
    print('Observability cache refresher started')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        shutdown_all()
