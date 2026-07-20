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
