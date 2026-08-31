import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.auth import _openai_compat_thinking_levels, build_openai_compatibility_block
from backend.model_thinking import (
    load_model_thinking_configs,
    save_model_thinking_configs,
    looks_thinking_capable,
    collect_thinking_candidates,
)


class TestModelThinkingConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / 'model_thinking_configs.json'
        self.patcher = patch('backend.model_thinking.MODEL_THINKING_CONFIGS_FILE', self.test_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_save_and_load_thinking_configs_with_levels(self):
        payload = {
            'configs': {
                'custom-sol': {
                    'mode': 'default',
                    'reasoning_effort': 'high',
                    'thinking_budget': 4096,
                    'thinking_levels': ['low', 'medium', 'high', 'xhigh', 'max'],
                },
                'custom-r1': {
                    'mode': 'force_on',
                    'reasoning_effort': '',
                    'thinking_budget': '',
                    'thinking_levels': 'low, medium, high, xhigh, max',
                },
                'default-model': {
                    'mode': 'default',
                    'reasoning_effort': '',
                    'thinking_budget': None,
                    'thinking_levels': None,
                },
            }
        }
        res = save_model_thinking_configs(payload)
        self.assertIn('custom-sol', res['configs'])
        self.assertIn('custom-r1', res['configs'])
        self.assertNotIn('default-model', res['configs'])

        loaded = load_model_thinking_configs()
        self.assertEqual(loaded['configs']['custom-sol']['thinking_levels'], ['low', 'medium', 'high', 'xhigh', 'max'])
        self.assertEqual(loaded['configs']['custom-sol']['thinking_budget'], 4096)
        self.assertEqual(loaded['configs']['custom-sol']['reasoning_effort'], 'high')
        self.assertEqual(loaded['configs']['custom-r1']['thinking_levels'], ['low', 'medium', 'high', 'xhigh', 'max'])
        self.assertEqual(loaded['configs']['custom-r1']['mode'], 'force_on')

    def test_openai_compat_thinking_levels_prefers_user_config(self):
        payload = {
            'configs': {
                'my-custom-model': {
                    'mode': 'default',
                    'thinking_levels': ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'],
                },
            }
        }
        save_model_thinking_configs(payload)

        # 1. Custom model gets user configured levels
        levels = _openai_compat_thinking_levels('my-custom-model')
        self.assertEqual(levels, ('minimal', 'low', 'medium', 'high', 'xhigh', 'max'))

        # 2. Built-in allowlisted model still gets built-in levels
        built_in_levels = _openai_compat_thinking_levels('gpt-5.6-sol')
        self.assertEqual(built_in_levels, ('low', 'medium', 'high', 'xhigh', 'max'))

        # 3. Unknown model gets empty tuple
        unknown_levels = _openai_compat_thinking_levels('unknown-random-model')
        self.assertEqual(unknown_levels, ())

    def test_build_openai_compatibility_block_includes_custom_thinking_levels(self):
        payload = {
            'configs': {
                'custom-o3': {
                    'mode': 'default',
                    'thinking_levels': ['low', 'medium', 'high', 'xhigh', 'max'],
                },
            }
        }
        save_model_thinking_configs(payload)

        entries = [{
            'provider': 'custom-openai',
            'base_url': 'https://example.invalid/v1',
            'api_key': 'test-key',
            'models': [
                'custom-o3',
                'custom-unconfigured',
            ],
        }]

        with patch('backend.auth._load_model_mapping_overrides', return_value={}):
            rendered = build_openai_compatibility_block(entries)

        self.assertIn('name: "custom-o3"', rendered)
        self.assertIn('levels: ["low", "medium", "high", "xhigh", "max"]', rendered)
        self.assertIn('name: "custom-unconfigured"', rendered)

    def test_looks_thinking_capable_heuristics(self):
        self.assertTrue(looks_thinking_capable('deepseek-r1'))
        self.assertTrue(looks_thinking_capable('gpt-5.6-sol'))
        self.assertTrue(looks_thinking_capable('o3-mini'))
        self.assertTrue(looks_thinking_capable('claude-3-7-sonnet'))
        self.assertFalse(looks_thinking_capable('text-davinci-003'))

    def test_collect_thinking_candidates_returns_all_providers(self):
        mock_provider_models = [
            {
                'provider': 'agnes',
                'rows': [{'call_id': 'agnes-gpt-4o', 'upstream_id': 'gpt-4o'}],
            },
            {
                'provider': 'glm',
                'rows': [{'call_id': 'glm-4-plus', 'upstream_id': 'glm-4-plus'}],
            },
        ]
        with patch('backend.auth.get_configured_provider_models', return_value=mock_provider_models), \
             patch('backend.auth.get_configured_aggregate_models', return_value=[]):
            candidates = collect_thinking_candidates()

        providers = {c['provider'] for c in candidates}
        self.assertIn('agnes', providers)
        self.assertIn('glm', providers)
        self.assertEqual(len(candidates), 3)  # agnes-gpt-4o, gpt-4o, glm-4-plus


    def test_openai_compat_thinking_levels_explicit_empty(self):
        payload = {
            'configs': {
                'gpt-5.6-sol': {
                    'mode': 'default',
                    'thinking_levels': [],
                },
            }
        }
        save_model_thinking_configs(payload)

        # When explicitly configured with empty list, does not fall back to built-in allowlist
        levels = _openai_compat_thinking_levels('gpt-5.6-sol')
        self.assertEqual(levels, ())

    def test_save_empty_or_reset_configs(self):
        payload = {'configs': {}}
        res = save_model_thinking_configs(payload)
        self.assertEqual(res['configs'], {})
        loaded = load_model_thinking_configs()
        self.assertEqual(loaded['configs'], {})


if __name__ == '__main__':
    unittest.main()

