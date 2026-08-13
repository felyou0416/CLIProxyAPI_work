import json
from pathlib import Path


def send_json(handler, payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(data)))
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(data)


def send_file(handler, path, content_type='text/html; charset=utf-8', *, root=None, download_name=None, extra_headers=None):
    target = Path(path)
    if root is not None:
        base = Path(root).resolve()
        resolved = target.resolve()
        try:
            resolved.relative_to(base)
        except ValueError:
            send_json(handler, {'ok': False, 'message': 'File path is outside the dashboard root.'}, status=403)
            return
        target = resolved
    if not target.exists() or not target.is_file():
        send_json(handler, {'ok': False, 'message': 'File not found.'}, status=404)
        return
    data = target.read_bytes()
    handler.send_response(200)
    handler.send_header('Content-Type', content_type)
    handler.send_header('Content-Length', str(len(data)))
    if download_name:
        safe_name = str(download_name).replace('"', '').replace('\n', '').replace('\r', '') or target.name
        handler.send_header('Content-Disposition', f'attachment; filename="{safe_name}"')
    for key, value in (extra_headers or {}).items():
        if key and value is not None:
            handler.send_header(str(key), str(value))
    handler.end_headers()
    handler.wfile.write(data)


def send_bytes(handler, data: bytes, content_type='application/octet-stream', *, status=200, download_name=None, extra_headers=None):
    payload = data if isinstance(data, (bytes, bytearray)) else bytes(data or b'')
    handler.send_response(status)
    handler.send_header('Content-Type', content_type)
    handler.send_header('Content-Length', str(len(payload)))
    if download_name:
        safe_name = str(download_name).replace('"', '').replace('\n', '').replace('\r', '') or 'download.bin'
        handler.send_header('Content-Disposition', f'attachment; filename="{safe_name}"')
    for key, value in (extra_headers or {}).items():
        if key and value is not None:
            handler.send_header(str(key), str(value))
    handler.end_headers()
    handler.wfile.write(payload)
