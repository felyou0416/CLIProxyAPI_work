import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.request_monitoring_config import request_monitoring_enabled
from backend.routes import get_routes, post_routes


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


def _payload(handler):
    return json.loads(handler.wfile.getvalue().decode('utf-8'))


class AdvancedConfigRouteTests(unittest.TestCase):
    def test_get_returns_complete_monitoring_config_with_bounded_values(self):
        state = {
            'request_monitoring_enabled': 'false',
            'request_observability_refresh_seconds': 1,
            'request_events_cache_ttl_seconds': 9999,
            'request_log_keep_files': 1,
            'request_event_archive_keep_entries': 9999999,
        }
        handler = _FakeHandler()
        with patch.object(get_routes, 'load_state', return_value=state):
            handled = get_routes.handle_get(
                handler,
                SimpleNamespace(path='/api/advanced-config', query=''),
            )

        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        item = _payload(handler)['item']
        self.assertFalse(item['request_monitoring_enabled'])
        self.assertEqual(item['request_observability_refresh_seconds'], 5)
        self.assertEqual(item['request_events_cache_ttl_seconds'], 300)
        self.assertEqual(item['request_log_keep_files'], 50)
        self.assertEqual(item['request_event_archive_keep_entries'], 1000000)

    def test_post_saves_monitoring_settings_without_runtime_only_options(self):
        current_state = {
            'core_routing_strategy': 'round-robin',
            'request_monitoring_enabled': True,
        }
        saved_state = {}
        handler = _FakeHandler()
        payload = {
            'request_monitoring_enabled': False,
            'request_observability_refresh_seconds': 60,
            'request_events_cache_ttl_seconds': 120,
            'request_log_keep_files': 500,
            'request_event_archive_keep_entries': 30000,
        }

        def save_state(state):
            saved_state.update(state)

        with patch.object(post_routes, 'load_state', return_value=dict(current_state)), \
             patch.object(post_routes, 'save_state', side_effect=save_state), \
             patch.object(post_routes, 'rebuild_runtime_config_from_state', return_value={'rebuilt': True}):
            handled = post_routes.handle_post(
                handler,
                SimpleNamespace(path='/api/advanced-config'),
                payload,
            )

        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        self.assertTrue(_payload(handler)['ok'])
        self.assertFalse(saved_state['request_monitoring_enabled'])
        self.assertEqual(saved_state['request_observability_refresh_seconds'], 60)
        self.assertEqual(saved_state['request_events_cache_ttl_seconds'], 120)
        self.assertEqual(saved_state['request_log_keep_files'], 500)
        self.assertEqual(saved_state['request_event_archive_keep_entries'], 30000)
        for key in (
            'request_observability_refresh_seconds',
            'request_events_cache_ttl_seconds',
            'request_log_keep_files',
            'request_event_archive_keep_entries',
        ):
            self.assertNotIn(key.replace('_', '-'), saved_state)

    def test_post_rejects_monitoring_values_outside_bounds(self):
        for key, value in (
            ('request_observability_refresh_seconds', 4),
            ('request_events_cache_ttl_seconds', 301),
            ('request_log_keep_files', 49),
            ('request_event_archive_keep_entries', 1000001),
        ):
            handler = _FakeHandler()
            with patch.object(post_routes, 'load_state', return_value={'core_routing_strategy': 'round-robin'}), \
                 patch.object(post_routes, 'save_state') as save_state, \
                 patch.object(post_routes, 'rebuild_runtime_config_from_state') as rebuild:
                handled = post_routes.handle_post(
                    handler,
                    SimpleNamespace(path='/api/advanced-config'),
                    {key: value},
                )

            self.assertTrue(handled)
            self.assertEqual(handler.status, 400)
            self.assertFalse(_payload(handler)['ok'])
            save_state.assert_not_called()
            rebuild.assert_not_called()


class RequestMonitoringConfigTests(unittest.TestCase):
    def test_enabled_without_explicit_state_reads_current_config(self):
        with patch(
            'backend.request_monitoring_config.load_request_monitoring_config',
            return_value={'request_monitoring_enabled': False},
        ):
            self.assertFalse(request_monitoring_enabled())


if __name__ == '__main__':
    unittest.main()
