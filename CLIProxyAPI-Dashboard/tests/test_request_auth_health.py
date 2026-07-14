import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.request_metrics.summary import summarize_auth_health


class RequestAuthHealthTests(unittest.TestCase):
    def test_summarize_auth_health_uses_clear_probe_states(self):
        auth_items = [
            {'id': 'ok', 'name': 'ok.json', 'provider': 'ok'},
            {'id': 'mixed', 'name': 'mixed.json', 'provider': 'mixed'},
            {'id': 'down', 'name': 'down.json', 'provider': 'down'},
            {'id': 'unknown', 'name': 'unknown.json', 'provider': 'unknown'},
        ]
        provider_models = [
            {'provider': 'ok', 'rows': [{'call_id': 'ok/model'}]},
            {'provider': 'mixed', 'rows': [{'call_id': 'mixed/good'}, {'call_id': 'mixed/bad'}]},
            {'provider': 'down', 'rows': [{'call_id': 'down/model'}]},
        ]
        runtime_test_state = {
            'results': {
                'ok/model': {'available': True},
                'mixed/good': {'available': True},
                'mixed/bad': {'available': False},
                'down/model': {'available': False},
            }
        }

        rows = summarize_auth_health(auth_items, [], provider_models, runtime_test_state)
        states = {row['provider']: row['state'] for row in rows}

        self.assertEqual(states['ok'], 'healthy')
        self.assertEqual(states['mixed'], 'degraded')
        self.assertEqual(states['down'], 'failed')
        self.assertEqual(states['unknown'], 'unknown')


if __name__ == '__main__':
    unittest.main()
