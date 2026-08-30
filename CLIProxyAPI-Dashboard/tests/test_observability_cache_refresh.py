import threading
import time
import unittest
from unittest.mock import patch


class ObservabilityCacheRefreshTests(unittest.TestCase):
    def setUp(self):
        from backend.request_metrics import observability as obs

        self.obs = obs
        with obs._OBSERVABILITY_CACHE_COND:
            obs._OBSERVABILITY_CACHE.update({
                'ready': False,
                'refreshing': False,
                'refreshed_at': 0.0,
                'generation': 0,
                'events': [],
                'clients': [],
                'auth_health': [],
            })

    def test_request_event_snapshot_is_stable_and_reused_until_refresh(self):
        obs = self.obs
        with obs._REQUEST_EVENTS_CACHE_COND:
            obs._REQUEST_EVENTS_CACHE.update({
                'ready': False,
                'refreshing': False,
                'refreshed_at': 0.0,
                'generation': 0,
                'expires_at': 0.0,
                'events': [],
            })

        proxy_events = [
            {'request_id': 'b', 'timestamp': 200, 'path': '/v1/messages'},
            {'request_id': 'a', 'timestamp': 200, 'path': '/v1/messages'},
        ]
        with patch.object(obs, 'parse_proxy_requests', return_value=proxy_events) as proxy, \
             patch.object(obs, 'parse_precise_request_events', return_value=[]), \
             patch.object(obs, 'parse_error_logs', return_value=[]), \
             patch.object(obs, 'get_configured_provider_models', return_value=[]), \
             patch.object(obs, 'merge_request_events', side_effect=lambda proxy, precise, errors, models: proxy):
            first = obs.get_request_events_cache()
            second = obs.get_request_events_cache()

        self.assertEqual([item['request_id'] for item in first['events']], ['a', 'b'])
        self.assertEqual(second['generation'], first['generation'])
        self.assertEqual(proxy.call_count, 1)

    def test_request_event_snapshot_starts_in_background_without_waiting(self):
        obs = self.obs
        with obs._REQUEST_EVENTS_CACHE_COND:
            obs._REQUEST_EVENTS_CACHE.update({
                'ready': False,
                'refreshing': False,
                'refreshed_at': 0.0,
                'generation': 0,
                'expires_at': 0.0,
                'events': [],
            })

        started = threading.Event()
        release = threading.Event()

        def slow_parse(*_args, **_kwargs):
            started.set()
            self.assertTrue(release.wait(timeout=2), 'background rebuild never released')
            return [{'request_id': 'fresh', 'timestamp': 200, 'path': '/v1/messages'}]

        with patch.object(obs, 'parse_proxy_requests', side_effect=slow_parse), \
             patch.object(obs, 'parse_precise_request_events', return_value=[]), \
             patch.object(obs, 'parse_error_logs', return_value=[]), \
             patch.object(obs, 'get_configured_provider_models', return_value=[]), \
             patch.object(obs, 'merge_request_events', side_effect=lambda proxy, precise, errors, models: proxy):
            started_at = time.monotonic()
            pending = obs.get_request_events_cache(wait=False)
            self.assertLess(time.monotonic() - started_at, 0.25)
            self.assertTrue(pending['refreshing'])
            self.assertFalse(pending['ready'])
            self.assertTrue(started.wait(timeout=2), 'background rebuild never started')
            release.set()
            deadline = time.monotonic() + 2
            while obs.get_request_events_cache(wait=False).get('refreshing') and time.monotonic() < deadline:
                time.sleep(0.01)
            ready = obs.get_request_events_cache()

        self.assertTrue(ready['ready'])
        self.assertFalse(ready['refreshing'])
        self.assertEqual([item['request_id'] for item in ready['events']], ['fresh'])

    def test_request_event_refresh_keeps_previous_snapshot_until_rebuilt(self):
        obs = self.obs
        with obs._REQUEST_EVENTS_CACHE_COND:
            obs._REQUEST_EVENTS_CACHE.update({
                'ready': True,
                'refreshing': False,
                'refreshed_at': 100.0,
                'generation': 3,
                'expires_at': time.time() + 30.0,
                'events': [{'request_id': 'old', 'timestamp': 100, 'path': '/v1/messages'}],
            })

        started = threading.Event()
        release = threading.Event()

        def slow_parse(*_args, **_kwargs):
            started.set()
            self.assertTrue(release.wait(timeout=2), 'background rebuild never released')
            return [{'request_id': 'new', 'timestamp': 200, 'path': '/v1/messages'}]

        with patch.object(obs, 'parse_proxy_requests', side_effect=slow_parse), \
             patch.object(obs, 'parse_precise_request_events', return_value=[]), \
             patch.object(obs, 'parse_error_logs', return_value=[]), \
             patch.object(obs, 'get_configured_provider_models', return_value=[]), \
             patch.object(obs, 'merge_request_events', side_effect=lambda proxy, precise, errors, models: proxy):
            pending = obs.get_request_events_cache(force=True, wait=False)
            self.assertTrue(started.wait(timeout=2), 'background rebuild never started')
            self.assertTrue(pending['ready'])
            self.assertTrue(pending['refreshing'])
            self.assertEqual([item['request_id'] for item in pending['events']], ['old'])
            self.assertEqual(pending['generation'], 3)
            release.set()
            deadline = time.monotonic() + 2
            while obs.get_request_events_cache(wait=False).get('refreshing') and time.monotonic() < deadline:
                time.sleep(0.01)
            rebuilt = obs.get_request_events_cache()

        self.assertTrue(rebuilt['ready'])
        self.assertFalse(rebuilt['refreshing'])
        self.assertEqual([item['request_id'] for item in rebuilt['events']], ['new'])
        self.assertEqual(rebuilt['generation'], 4)

    def test_disabled_monitoring_does_not_parse_request_logs(self):
        obs = self.obs
        with patch.object(obs, 'request_monitoring_enabled', return_value=False), \
             patch.object(obs, 'parse_proxy_requests') as proxy, \
             patch.object(obs, 'parse_precise_request_events') as precise, \
             patch.object(obs, 'parse_error_logs') as errors:
            snapshot = obs.build_observability_snapshot()
            table = obs.get_request_events_cache()

        self.assertTrue(snapshot['disabled'])
        self.assertEqual(snapshot['events'], [])
        self.assertTrue(table['disabled'])
        self.assertEqual(table['events'], [])
        proxy.assert_not_called()
        precise.assert_not_called()
        errors.assert_not_called()

    def test_request_event_cache_uses_configured_ttl(self):
        obs = self.obs
        with obs._REQUEST_EVENTS_CACHE_COND:
            obs._REQUEST_EVENTS_CACHE.update({
                'ready': False,
                'refreshing': False,
                'refreshed_at': 0.0,
                'generation': 0,
                'expires_at': 0.0,
                'events': [],
            })

        config = {
            'request_monitoring_enabled': True,
            'request_events_cache_ttl_seconds': 123,
            'request_observability_refresh_seconds': 15,
            'request_log_keep_files': 300,
            'request_event_archive_keep_entries': 20000,
        }
        with patch.object(obs, 'load_request_monitoring_config', return_value=config), \
             patch.object(obs, 'request_monitoring_enabled', return_value=True), \
             patch.object(obs, 'parse_proxy_requests', return_value=[]), \
             patch.object(obs, 'parse_precise_request_events', return_value=[]), \
             patch.object(obs, 'parse_error_logs', return_value=[]), \
             patch.object(obs, 'get_configured_provider_models', return_value=[]), \
             patch.object(obs, 'merge_request_events', return_value=[]):
            result = obs.get_request_events_cache()

        self.assertEqual(result['events'], [])
        with obs._REQUEST_EVENTS_CACHE_COND:
            self.assertGreater(obs._REQUEST_EVENTS_CACHE['expires_at'], time.time() + 120)

    def test_monitoring_can_be_reenabled_after_disabled_cache(self):
        obs = self.obs
        with patch.object(obs, 'request_monitoring_enabled', return_value=False):
            disabled = obs.get_request_events_cache()
        self.assertTrue(disabled['disabled'])

        with patch.object(obs, 'request_monitoring_enabled', return_value=True), \
             patch.object(obs, 'parse_proxy_requests', return_value=[{'request_id': 'enabled', 'timestamp': 200}]), \
             patch.object(obs, 'parse_precise_request_events', return_value=[]), \
             patch.object(obs, 'parse_error_logs', return_value=[]), \
             patch.object(obs, 'get_configured_provider_models', return_value=[]), \
             patch.object(obs, 'merge_request_events', side_effect=lambda proxy, precise, errors, models: proxy):
            enabled = obs.get_request_events_cache(force=True)

        self.assertFalse(enabled['disabled'])
        self.assertEqual([item['request_id'] for item in enabled['events']], ['enabled'])

    def test_refresh_waits_for_in_flight_rebuild(self):
        obs = self.obs
        started = threading.Event()
        release = threading.Event()
        call_count = {'n': 0}

        def slow_snapshot():
            call_count['n'] += 1
            started.set()
            self.assertTrue(release.wait(timeout=2), 'refresh never released')
            return {
                'events': [{'id': call_count['n']}],
                'clients': [],
                'auth_health': [],
                'refreshed_at': 1000.0 + call_count['n'],
            }

        with patch.object(obs, 'build_observability_snapshot', side_effect=slow_snapshot):
            first_result = {}
            second_result = {}

            def run_first():
                first_result['value'] = obs.refresh_observability_cache()

            def run_second():
                self.assertTrue(started.wait(timeout=2), 'first refresh never started')
                second_result['value'] = obs.refresh_observability_cache()

            t1 = threading.Thread(target=run_first)
            t2 = threading.Thread(target=run_second)
            t1.start()
            t2.start()
            self.assertTrue(started.wait(timeout=2))
            time.sleep(0.05)
            release.set()
            t1.join(timeout=2)
            t2.join(timeout=2)

        self.assertTrue(t1.is_alive() is False)
        self.assertTrue(t2.is_alive() is False)
        self.assertEqual(call_count['n'], 1)
        self.assertEqual(first_result['value']['events'], [{'id': 1}])
        self.assertEqual(second_result['value']['events'], [{'id': 1}])
        self.assertTrue(second_result['value']['ready'])
        self.assertFalse(second_result['value']['refreshing'])

    def test_force_refresh_rebuilds_after_waiting(self):
        obs = self.obs
        started = threading.Event()
        release = threading.Event()
        call_count = {'n': 0}

        def slow_snapshot():
            call_count['n'] += 1
            if call_count['n'] == 1:
                started.set()
                self.assertTrue(release.wait(timeout=2), 'refresh never released')
            return {
                'events': [{'id': call_count['n']}],
                'clients': [],
                'auth_health': [],
                'refreshed_at': 2000.0 + call_count['n'],
            }

        with patch.object(obs, 'build_observability_snapshot', side_effect=slow_snapshot):
            first_result = {}
            force_result = {}

            def run_first():
                first_result['value'] = obs.refresh_observability_cache()

            def run_force():
                self.assertTrue(started.wait(timeout=2), 'first refresh never started')
                force_result['value'] = obs.refresh_observability_cache(force=True)

            t1 = threading.Thread(target=run_first)
            t2 = threading.Thread(target=run_force)
            t1.start()
            t2.start()
            self.assertTrue(started.wait(timeout=2))
            time.sleep(0.05)
            release.set()
            t1.join(timeout=2)
            t2.join(timeout=2)

        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual(call_count['n'], 2)
        self.assertEqual(first_result['value']['events'], [{'id': 1}])
        self.assertEqual(force_result['value']['events'], [{'id': 2}])
        self.assertEqual(force_result['value']['generation'], 2)


if __name__ == '__main__':
    unittest.main()
