import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.request_metrics.summary import (
    merge_cumulative_model_test_stats,
    resolve_model_stats_provider,
)


class CumulativeMigrationTests(unittest.TestCase):
    def test_v3_migration_preserves_historical_stats(self):
        from backend.request_metrics import cumulative

        original = {
            'version': 3,
            'updated_at': 100,
            'last_event_ts': 90,
            'totals': {'request_count': 12, 'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120},
            'by_model': {'old-model': {'request_count': 12, 'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}},
            'by_client': {},
            'by_provider': {},
            'daily': {'2026-07-01': {'request_count': 12, 'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}},
            'hourly': {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cumulative_token_stats.json'
            path.write_text(json.dumps(original), encoding='utf-8')
            with patch.object(cumulative, '_CUMULATIVE_FILE', path), patch.object(
                cumulative, '_save_stats', side_effect=lambda stats: path.write_text(json.dumps(stats), encoding='utf-8')
            ):
                migrated = cumulative._load_stats()

        self.assertEqual(migrated['version'], 4)
        self.assertEqual(migrated['totals'], original['totals'])
        self.assertEqual(migrated['by_model'], original['by_model'])
        self.assertEqual(migrated['daily'], original['daily'])


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
