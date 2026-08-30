import io
import json
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routes import get_routes


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

    def payload(self):
        return json.loads(self.wfile.getvalue().decode('utf-8'))


class RequestEventsRouteMetadataTests(unittest.TestCase):
    def _request(self, query=''):
        handler = _FakeHandler()
        handled = get_routes.handle_get(handler, SimpleNamespace(
            path='/api/request-events',
            query=query,
        ))
        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        return handler.payload()

    @patch.object(get_routes, 'get_request_events_cache', return_value={
        'generation': 7,
        'refreshed_at': 900.0,
        'ready': True,
        'refreshing': False,
        'events': [
            {'request_id': 'req-4', 'timestamp': 1234, 'path': '/v1/messages'},
            {'request_id': 'req-3', 'timestamp': 1233, 'path': '/v1/messages'},
            {'request_id': 'req-2', 'timestamp': 1232, 'path': '/v1/messages'},
            {'request_id': 'req-1', 'timestamp': 1231, 'path': '/v1/messages'},
        ],
    })
    def test_unfiltered_page_uses_one_complete_event_snapshot(self, cache):
        first_page = self._request('limit=2&offset=0')
        second_page = self._request('limit=2&offset=2')
        self.assertEqual(
            [item['request_id'] for item in first_page['items']],
            ['req-4', 'req-3'],
        )
        self.assertEqual(
            [item['request_id'] for item in second_page['items']],
            ['req-2', 'req-1'],
        )
        self.assertTrue(set(item['request_id'] for item in first_page['items']).isdisjoint(
            item['request_id'] for item in second_page['items']
        ))
        self.assertEqual(first_page['total'], 4)
        self.assertEqual(second_page['total'], 4)
        self.assertTrue(first_page['cached'])
        self.assertFalse(first_page['lazy'])
        self.assertEqual(first_page['data_source'], 'request-events-cache')
        self.assertEqual(first_page['data_as_of'], 1234)
        self.assertEqual(first_page['refreshed_at'], 900.0)
        self.assertEqual(first_page['cache_generation'], 7)
        cache.assert_called_with(force=False, wait=False)

    @patch.object(get_routes, 'get_request_events_cache', return_value={
        'generation': 3,
        'refreshed_at': 1234.0,
        'ready': True,
        'refreshing': True,
        'events': [
            {'request_id': 'old-2', 'timestamp': 1234, 'path': '/v1/messages'},
            {'request_id': 'old-1', 'timestamp': 1233, 'path': '/v1/messages'},
        ],
    })
    def test_refreshing_snapshot_keeps_the_requested_old_page(self, cache):
        data = self._request('limit=1&offset=1&refresh=1')
        self.assertEqual([item['request_id'] for item in data['items']], ['old-1'])
        self.assertEqual(data['total'], 2)
        self.assertTrue(data['cached'])
        self.assertTrue(data['refreshing'])
        self.assertEqual(data['cache_generation'], 3)
        cache.assert_called_with(force=True, wait=False)

    @patch.object(get_routes, 'get_request_events_cache', return_value={
        'generation': 12,
        'refreshed_at': 4321.0,
        'ready': True,
        'refreshing': False,
        'events': [
            {
                'request_id': 'alpha-2',
                'timestamp': 4321,
                'path': '/v1/messages',
                'requested_model': 'alpha',
                'client_ip': '127.0.0.1',
                'inferred_provider': 'demo',
                'status_code': 200,
                'success': True,
            },
            {
                'request_id': 'beta',
                'timestamp': 4320,
                'path': '/v1/messages',
                'requested_model': 'beta',
                'client_ip': '127.0.0.1',
                'inferred_provider': 'demo',
                'status_code': 200,
                'success': True,
            },
            {
                'request_id': 'alpha-1',
                'timestamp': 4319,
                'path': '/v1/messages',
                'requested_model': 'alpha',
                'client_ip': '127.0.0.2',
                'inferred_provider': 'demo',
                'status_code': 200,
                'success': True,
            },
        ],
    })
    def test_filtered_page_uses_request_event_snapshot_metadata(self, cache):
        first_page = self._request('limit=1&offset=0&model=alpha')
        second_page = self._request('limit=1&offset=1&model=alpha')
        self.assertEqual(first_page['items'][0]['request_id'], 'alpha-2')
        self.assertEqual(second_page['items'][0]['request_id'], 'alpha-1')
        self.assertEqual(first_page['total'], 2)
        self.assertEqual(second_page['total'], 2)
        self.assertFalse(first_page['lazy'])
        self.assertEqual(first_page['data_source'], 'request-events-cache')
        self.assertEqual(first_page['refreshed_at'], 4321.0)
        self.assertEqual(first_page['cache_generation'], 12)
        self.assertFalse(first_page['refreshing'])
        cache.assert_called_with(force=False, wait=False)


if __name__ == '__main__':
    unittest.main()
