import io
import unittest

from backend.server import MAX_REQUEST_BYTES, _flatten_form_data, _read_request_data


class _FakeHandler:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self.headers = headers or {}
        self.rfile = io.BytesIO(body)


class ServerParsingTests(unittest.TestCase):
    def test_flatten_form_data_collapses_single_values(self):
        payload = _flatten_form_data('a=1&b=2&b=3&empty=')
        self.assertEqual(payload['a'], '1')
        self.assertEqual(payload['b'], ['2', '3'])
        self.assertEqual(payload['empty'], '')

    def test_read_request_data_parses_json(self):
        body = b'{"ok": true, "name": "demo"}'
        handler = _FakeHandler(body, {'Content-Length': str(len(body))})
        self.assertEqual(_read_request_data(handler), {'ok': True, 'name': 'demo'})

    def test_read_request_data_falls_back_to_form_payload(self):
        body = b'name=demo&tag=one&tag=two'
        handler = _FakeHandler(body, {'Content-Length': str(len(body))})
        self.assertEqual(_read_request_data(handler), {'name': 'demo', 'tag': ['one', 'two']})

    def test_read_request_data_rejects_large_payload(self):
        handler = _FakeHandler(b'', {'Content-Length': str(MAX_REQUEST_BYTES + 1)})
        with self.assertRaises(OverflowError):
            _read_request_data(handler)

    def test_read_request_data_rejects_invalid_content_length(self):
        handler = _FakeHandler(b'', {'Content-Length': 'abc'})
        with self.assertRaises(ValueError):
            _read_request_data(handler)
