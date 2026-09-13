import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from backend.routes import post_routes


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


class ChatStreamRouteTests(unittest.TestCase):
    def test_chat_route_streams_when_stream_true(self):
        handler = _FakeHandler()
        mock_chunks = [
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
            b'data: [DONE]\n\n',
        ]
        mock_resp = MagicMock()
        mock_resp.__iter__.return_value = mock_chunks
        mock_resp.close.return_value = None

        payload = {
            'model': 'claude-opus-5',
            'messages': [{'role': 'user', 'content': 'hi'}],
            'stream': True,
        }

        with patch('urllib.request.urlopen', return_value=mock_resp):
            handled = post_routes.handle_post(
                handler,
                SimpleNamespace(path='/api/chat'),
                payload,
            )

        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        self.assertIn('text/event-stream', handler.headers.get('Content-Type', ''))
        self.assertEqual(handler.wfile.getvalue(), b''.join(mock_chunks))

    def test_chat_route_non_stream_uses_proxy_request(self):
        handler = _FakeHandler()
        payload = {
            'model': 'claude-opus-5',
            'messages': [{'role': 'user', 'content': 'hi'}],
            'stream': False,
        }
        mock_proxy_result = {
            'ok': True,
            'status_code': 200,
            'body': json.dumps({'choices': [{'message': {'content': 'Hi there'}}]}),
        }

        with patch.object(post_routes, '_proxy_request', return_value=mock_proxy_result) as mock_proxy:
            handled = post_routes.handle_post(
                handler,
                SimpleNamespace(path='/api/chat'),
                payload,
            )

        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        mock_proxy.assert_called_once_with('/v1/chat/completions', payload)
        body = json.loads(handler.wfile.getvalue().decode('utf-8'))
        self.assertEqual(body['choices'][0]['message']['content'], 'Hi there')
