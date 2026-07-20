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


class PublicPathsTests(unittest.TestCase):
    def test_is_public_path(self):
        from backend.server import _is_public_path

        # Public shell + static UI assets (avoid 401 thrash on boot)
        self.assertTrue(_is_public_path('/'))
        self.assertTrue(_is_public_path('/index.html'))
        self.assertTrue(_is_public_path('/dashboard.css'))
        self.assertTrue(_is_public_path('/js/i18n.js'))
        self.assertTrue(_is_public_path('/js/core.js'))
        self.assertTrue(_is_public_path('/js/boot.js'))
        self.assertTrue(_is_public_path('/js/chat.js'))
        self.assertTrue(_is_public_path('/js/terminals.js'))
        self.assertTrue(_is_public_path('/css/atom-one-dark.min.css'))
        self.assertTrue(_is_public_path('/css/xterm.min.css'))
        self.assertTrue(_is_public_path('/sections/terminals.html'))
        self.assertTrue(_is_public_path('/sections/firewall-access.html'))
        self.assertTrue(_is_public_path('/generated/images/sample.png'))
        self.assertTrue(_is_public_path('/api/auth/login'))
        self.assertTrue(_is_public_path('/api/auth/check'))

        # API routes stay protected (when password gate is enabled)
        self.assertFalse(_is_public_path('/api/status'))
        self.assertFalse(_is_public_path('/api/terminals'))
        self.assertFalse(_is_public_path('/api/auth/sensitive/verify'))


class SensitiveAuthTests(unittest.TestCase):
    def test_check_sensitive_auth_allows_non_sensitive(self):
        from backend.server import _check_sensitive_auth
        from urllib.parse import urlparse
        
        class FakeHandler:
            headers = {}
            
        handler = FakeHandler()
        parsed = urlparse('/api/status')
        self.assertTrue(_check_sensitive_auth(handler, parsed))

    def test_check_sensitive_auth_blocks_sensitive_without_key(self):
        from unittest.mock import patch
        from backend.server import _check_sensitive_auth
        from urllib.parse import urlparse
        
        class FakeHandler:
            headers = {}
            wfile = io.BytesIO()
            def send_response(self, status): self.status = status
            def send_header(self, k, v): pass
            def end_headers(self): pass

        handler = FakeHandler()
        parsed = urlparse('/api/terminals')
        
        with patch('backend.state.load_state', return_value={'sensitive_auth_key': 'secret-123'}):
            self.assertFalse(_check_sensitive_auth(handler, parsed))
            self.assertEqual(handler.status, 403)

    def test_check_sensitive_auth_allows_sensitive_with_header_key(self):
        from unittest.mock import patch
        from backend.server import _check_sensitive_auth
        from urllib.parse import urlparse
        
        class FakeHandler:
            headers = {'X-Sensitive-Auth-Key': 'secret-123'}
            
        handler = FakeHandler()
        parsed = urlparse('/api/terminals')
        
        with patch('backend.state.load_state', return_value={'sensitive_auth_key': 'secret-123'}):
            self.assertTrue(_check_sensitive_auth(handler, parsed))

    def test_check_sensitive_auth_allows_sensitive_with_query_key(self):
        from unittest.mock import patch
        from backend.server import _check_sensitive_auth
        from urllib.parse import urlparse
        
        class FakeHandler:
            headers = {}
            
        handler = FakeHandler()
        parsed = urlparse('/api/terminals/output?sensitive_key=secret-123')
        
        with patch('backend.state.load_state', return_value={'sensitive_auth_key': 'secret-123'}):
            self.assertTrue(_check_sensitive_auth(handler, parsed))


