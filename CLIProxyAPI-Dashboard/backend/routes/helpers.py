import json
from pathlib import Path


def send_json(handler, payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def send_file(handler, path, content_type='text/html; charset=utf-8', *, root=None):
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
    handler.end_headers()
    handler.wfile.write(data)
