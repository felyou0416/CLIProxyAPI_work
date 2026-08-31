import pathlib
import tempfile
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

    def _reset_request_events_cache(self, **updates):
        defaults = {
            'ready': False,
            'refreshing': False,
            'refreshed_at': 0.0,
            'generation': 0,
            'expires_at': 0.0,
            'source_signatures': None,
            'events': [],
        }
        defaults.update(updates)
        with self.obs._REQUEST_EVENTS_CACHE_COND:
            self.obs._REQUEST_EVENTS_CACHE.update(defaults)

    def test_request_event_cache_invalidates_for_each_log_source_change(self):
        obs = self.obs
        config = {
            'request_monitoring_enabled': True,
            'request_events_cache_ttl_seconds': 300,
            'request_observability_refresh_seconds': 15,
            'request_log_keep_files': 300,
            'request_event_archive_keep_entries': 20000,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            log_dir = root / 'logs'
            archive_dir = root / 'archive'
            log_dir.mkdir()
            archive_dir.mkdir()
            stdout_path = root / 'proxy.stdout.log'
            precise_path = log_dir / 'request-1.log'
            error_path = log_dir / 'error-1.log'
            archive_path = archive_dir / 'request-events-1.jsonl'

            self._reset_request_events_cache()
            with patch.object(obs, '_request_log_dirs', return_value=[log_dir]), \
                 patch.object(obs, 'PROXY_STDOUT', stdout_path), \
                 patch.object(obs, 'REQUEST_ARCHIVE_DIR', archive_dir), \
                 patch.object(obs, 'request_monitoring_enabled', return_value=True), \
                 patch.object(obs, 'load_request_monitoring_config', return_value=config), \
                 patch.object(obs, 'parse_proxy_requests', return_value=[]), \
                 patch.object(obs, 'parse_precise_request_events', return_value=[]), \
                 patch.object(obs, 'parse_error_logs', return_value=[]), \
                 patch.object(obs, 'get_configured_provider_models', return_value=[]), \
                 patch.object(obs, 'merge_request_events', return_value=[]) as merge:
                generation = 0

                def refresh_after_change():
                    nonlocal generation
                    snapshot = obs.get_request_events_cache(wait=True)
                    generation += 1
                    self.assertFalse(snapshot['refreshing'])
                    self.assertEqual(snapshot['generation'], generation)

                refresh_after_change()

                precise_path.write_text('first', encoding='utf-8')
                refresh_after_change()
                with precise_path.open('a', encoding='utf-8') as stream:
                    stream.write('-append')
                refresh_after_change()

                error_path.write_text('first error', encoding='utf-8')
                refresh_after_change()
                with error_path.open('a', encoding='utf-8') as stream:
                    stream.write('-append')
                refresh_after_change()

                stdout_path.write_text('first stdout', encoding='utf-8')
                refresh_after_change()
                with stdout_path.open('a', encoding='utf-8') as stream:
                    stream.write('-append')
                refresh_after_change()

                archive_path.write_text('first archive', encoding='utf-8')
                refresh_after_change()
                with archive_path.open('a', encoding='utf-8') as stream:
                    stream.write('-append')
                refresh_after_change()

                archive_path.unlink()
                refresh_after_change()

            self.assertEqual(merge.call_count, generation)

    def test_request_event_cache_rechecks_changes_made_during_rebuild(self):
        obs = self.obs
        config = {
            'request_monitoring_enabled': True,
            'request_events_cache_ttl_seconds': 300,
            'request_observability_refresh_seconds': 15,
            'request_log_keep_files': 300,
            'request_event_archive_keep_entries': 20000,
        }
        started = threading.Event()
        release = threading.Event()
        second_started = threading.Event()
        parse_calls = {'count': 0}

        def slow_parse(*_args, **_kwargs):
            parse_calls['count'] += 1
            if parse_calls['count'] == 1:
                started.set()
                if not release.wait(timeout=2):
                    raise RuntimeError('rebuild was not released')
            elif parse_calls['count'] == 2:
                second_started.set()
            return [{
                'request_id': f'rebuilt-{parse_calls["count"]}',
                'timestamp': 200 + parse_calls['count'],
                'path': '/v1/messages',
            }]

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            log_dir = root / 'logs'
            archive_dir = root / 'archive'
            log_dir.mkdir()
            archive_dir.mkdir()
            stdout_path = root / 'proxy.stdout.log'
            stdout_path.write_text('initial', encoding='utf-8')

            self._reset_request_events_cache()
            with patch.object(obs, '_request_log_dirs', return_value=[log_dir]), \
                 patch.object(obs, 'PROXY_STDOUT', stdout_path), \
                 patch.object(obs, 'REQUEST_ARCHIVE_DIR', archive_dir), \
                 patch.object(obs, 'request_monitoring_enabled', return_value=True), \
                 patch.object(obs, 'load_request_monitoring_config', return_value=config), \
                 patch.object(obs, 'parse_proxy_requests', side_effect=slow_parse), \
                 patch.object(obs, 'parse_precise_request_events', return_value=[]), \
                 patch.object(obs, 'parse_error_logs', return_value=[]), \
                 patch.object(obs, 'get_configured_provider_models', return_value=[]), \
                 patch.object(obs, 'merge_request_events', side_effect=lambda proxy, precise, errors, models: proxy):
                initial_signatures = obs._request_log_source_signatures()
                self._reset_request_events_cache(
                    ready=True,
                    refreshed_at=time.time(),
                    generation=10,
                    expires_at=time.time() + 300,
                    source_signatures=initial_signatures,
                    events=[{'request_id': 'old'}],
                )

                pending = obs.get_request_events_cache(force=True, wait=False)
                self.assertTrue(pending['refreshing'])
                self.assertTrue(started.wait(timeout=2), 'background rebuild never started')

                with stdout_path.open('a', encoding='utf-8') as stream:
                    stream.write('-written-during-rebuild')
                release.set()

                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    with obs._REQUEST_EVENTS_CACHE_COND:
                        refreshing = bool(obs._REQUEST_EVENTS_CACHE.get('refreshing'))
                    if not refreshing:
                        break
                    time.sleep(0.01)

                with obs._REQUEST_EVENTS_CACHE_COND:
                    self.assertFalse(obs._REQUEST_EVENTS_CACHE['refreshing'])
                    self.assertEqual(obs._REQUEST_EVENTS_CACHE['generation'], 11)
                    self.assertEqual(obs._REQUEST_EVENTS_CACHE['source_signatures'], initial_signatures)

                obs.get_request_events_cache(wait=False)
                self.assertTrue(second_started.wait(timeout=2), 'second rebuild never started')

                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    with obs._REQUEST_EVENTS_CACHE_COND:
                        refreshing = bool(obs._REQUEST_EVENTS_CACHE.get('refreshing'))
                    if not refreshing:
                        break
                    time.sleep(0.01)
                final = obs.get_request_events_cache(wait=True)

        self.assertFalse(final['refreshing'])
        self.assertEqual(final['generation'], 12)
        self.assertEqual([item['request_id'] for item in final['events']], ['rebuilt-2'])
        self.assertEqual(parse_calls['count'], 2)

    def test_request_event_snapshot_is_stable_and_reused_until_refresh(self):
        obs = self.obs
        with obs._REQUEST_EVENTS_CACHE_COND:
            obs._REQUEST_EVENTS_CACHE.update({
                'ready': False,
                'refreshing': False,
                'refreshed_at': 0.0,
                'generation': 0,
                'expires_at': 0.0,
                'source_signatures': None,
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
                'source_signatures': None,
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
                'source_signatures': None,
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
