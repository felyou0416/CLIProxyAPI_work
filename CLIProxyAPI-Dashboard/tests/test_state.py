import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import state


class StateTests(unittest.TestCase):
    def test_normalize_route_strategy_handles_string_inputs(self):
        normalized = state.normalize_route_strategy(
            {
                'enabled': 'false',
                'aggregate_only': 'true',
                'probe_parallelism': '99',
                'cooldown_default_seconds': 'oops',
                'cooldown_timeout_seconds': '-10',
            }
        )
        self.assertFalse(normalized['enabled'])
        self.assertTrue(normalized['aggregate_only'])
        self.assertEqual(normalized['probe_parallelism'], 24)
        self.assertEqual(normalized['cooldown_default_seconds'], state.default_route_strategy()['cooldown_default_seconds'])
        self.assertEqual(normalized['cooldown_timeout_seconds'], 0)

    def test_save_state_writes_atomically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / 'state.json'
            with patch.object(state, 'STATE_FILE', state_path):
                payload = {'selected_auth': 'demo'}
                state.save_state(payload)
                self.assertTrue(state_path.exists())
                saved = json.loads(state_path.read_text(encoding='utf-8'))
                self.assertEqual(saved['selected_auth'], payload['selected_auth'])
                self.assertIn('last_runtime_config', saved)
                self.assertIn('last_active_auth_dir', saved)
                self.assertFalse(state_path.with_suffix('.tmp').exists())

    def test_load_state_recovers_from_invalid_strategy_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / 'state.json'
            state_path.write_text(
                json.dumps(
                    {
                        'route_strategy': {
                            'enabled': 'yes',
                            'aggregate_only': 'no',
                            'probe_parallelism': 'bad',
                            'cooldown_client_seconds': 'bad',
                        }
                    }
                ),
                encoding='utf-8',
            )
            with patch.object(state, 'STATE_FILE', state_path):
                loaded = state.load_state()
        self.assertTrue(loaded['route_strategy']['enabled'])
        self.assertFalse(loaded['route_strategy']['aggregate_only'])
        self.assertEqual(loaded['route_strategy']['probe_parallelism'], state.default_route_strategy()['probe_parallelism'])
        self.assertEqual(loaded['route_strategy']['cooldown_client_seconds'], state.default_route_strategy()['cooldown_client_seconds'])
