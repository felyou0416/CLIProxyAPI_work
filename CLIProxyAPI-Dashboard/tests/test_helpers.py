import io
import tempfile
import unittest
from pathlib import Path

from backend.routes.helpers import send_file, send_json


class _FakeHandler:
    def __init__(self):
        self.status = None
        self.headers = {}
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        return None


class SendFileTests(unittest.TestCase):
    def test_send_json_disables_response_caching(self):
        handler = _FakeHandler()
        send_json(handler, {'ok': True})
        self.assertEqual(handler.headers['Cache-Control'], 'no-store')

    def test_send_file_serves_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / 'index.html'
            file_path.write_text('hello', encoding='utf-8')
            handler = _FakeHandler()
            send_file(handler, file_path, root=root)
            self.assertEqual(handler.status, 200)
            self.assertEqual(handler.wfile.getvalue(), b'hello')

    def test_send_file_rejects_path_outside_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outside = root.parent / 'outside.txt'
            outside.write_text('blocked', encoding='utf-8')
            handler = _FakeHandler()
            send_file(handler, outside, root=root)
            self.assertEqual(handler.status, 403)

    def test_send_file_returns_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            handler = _FakeHandler()
            send_file(handler, root / 'missing.txt', root=root)
            self.assertEqual(handler.status, 404)
