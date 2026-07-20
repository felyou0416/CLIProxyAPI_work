import unittest
from unittest.mock import patch

from backend.request_metrics.summary import (
    merge_cumulative_model_test_stats,
    resolve_model_stats_provider,
)


class ModelStatsHistoricalTests(unittest.TestCase):
    def test_guess_provider_from_prefix(self):
        with patch('backend.request_metrics.summary._override_model_lookup', return_value=({}, {}, {'groq', 'aihubmix'})):
            meta = resolve_model_stats_provider('groq-compound', [])
        self.assertEqual(meta['provider'], 'groq')
        self.assertTrue(meta['is_historical'])

    def test_override_call_id_resolution(self):
        ov_call = {'aihubmix-auto': 'aihubmix'}
        ov_up = {
            'aihubmix-auto': {
                'source_provider': 'aihubmix',
                'target_provider': 'aihubmix',
                'upstream_id': 'auto',
                'lookup_upstream_id': 'auto',
                'call_id': 'aihubmix-auto',
                'deleted': False,
            }
        }
        with patch(
            'backend.request_metrics.summary._override_model_lookup',
            return_value=(ov_call, ov_up, {'aihubmix'}),
        ):
            meta = resolve_model_stats_provider('aihubmix-auto', [])
        self.assertEqual(meta['provider'], 'aihubmix')
        self.assertEqual(meta['delete_upstream_id'], 'auto')
        self.assertTrue(meta['can_delete'])

    def test_unknown_becomes_historical(self):
        with patch('backend.request_metrics.summary._override_model_lookup', return_value=({}, {}, set())):
            meta = resolve_model_stats_provider('unknown', [])
        self.assertEqual(meta['provider'], '历史残留')
        self.assertTrue(meta['is_historical'])

    def test_merge_cumulative_appends_with_provider(self):
        rows = [{
            'model': 'codex5.5',
            'provider': 'codex',
            'delete_provider': 'codex',
            'delete_upstream_id': 'gpt-5.5',
            'actual_model': 'gpt-5.5',
            'can_delete': True,
            'prompt_tokens': 1,
            'completion_tokens': 1,
            'total_tokens': 2,
        }]
        cum = {
            'codex5.5': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30, 'request_count': 3},
            'groq-compound': {'prompt_tokens': 870, 'completion_tokens': 625, 'total_tokens': 1495, 'request_count': 1},
            'unknown': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0, 'request_count': 9},
        }
        with patch(
            'backend.request_metrics.summary._override_model_lookup',
            return_value=({}, {}, {'groq', 'codex'}),
        ):
            merged = merge_cumulative_model_test_stats(rows, cum, [])
        by_model = {item['model']: item for item in merged}
        self.assertEqual(by_model['codex5.5']['total_tokens'], 30)
        self.assertFalse(by_model['codex5.5']['is_historical'])
        self.assertEqual(by_model['groq-compound']['provider'], 'groq')
        self.assertTrue(by_model['groq-compound']['is_historical'])
        self.assertEqual(by_model['unknown']['provider'], '历史残留')
        self.assertTrue(by_model['unknown']['is_historical'])


if __name__ == '__main__':
    unittest.main()
