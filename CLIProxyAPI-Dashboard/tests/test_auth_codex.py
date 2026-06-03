import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import auth


class CodexAccessOnlyAuthTests(unittest.TestCase):
    def test_normalize_runtime_codex_oauth_content_without_refresh(self):
        payload = {
            'metadata': {
                'email': 'user@example.com',
                'provider': 'openai-codex',
            },
            'content': {
                'type': 'oauth',
                'provider': 'openai-codex',
                'access': 'access-token',
                'refresh': '',
                'accountId': 'acct_123',
                'plan': 'plus',
            },
        }

        auth_kind = auth._detect_auth_payload_kind(payload)
        normalized = auth._normalize_runtime_oauth_payload(payload, 'codex', auth_kind)

        self.assertEqual(auth_kind, 'codex_oauth_content')
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized['provider'], 'codex')
        self.assertEqual(normalized['access_token'], 'access-token')
        self.assertEqual(normalized['refresh_token'], '')
        self.assertEqual(normalized['account_id'], 'acct_123')

    def test_to_oauth_manager_codex_payload_without_refresh(self):
        payload = {
            'provider': 'codex',
            'type': 'codex',
            'access_token': 'access-token',
            'refresh_token': '',
            'account_id': 'acct_123',
            'email': 'user@example.com',
        }

        converted = auth._to_oauth_manager_codex_payload(payload, 'codex.json', 'test')

        self.assertEqual(converted['content']['provider'], 'openai-codex')
        self.assertEqual(converted['content']['access'], 'access-token')
        self.assertEqual(converted['content']['refresh'], '')
        self.assertEqual(converted['content']['accountId'], 'acct_123')


class ProviderModelMappingTests(unittest.TestCase):
    def test_old_format_override_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'provider_model_overrides.json'
            path.write_text(json.dumps({
                'codex': {
                    'gpt-test': {
                        'call_id': 'local-test',
                        'provider': 'codex',
                        'upstream_id': 'gpt-test',
                        'deleted': False,
                    }
                }
            }), encoding='utf-8')

            with patch.object(auth, 'MODEL_MAPPING_OVERRIDES_FILE', path):
                overrides = auth._load_model_mapping_overrides()
                mappings = auth.resolve_provider_mappings('codex', 'gpt-test', 'gpt-test', overrides=overrides)

            self.assertEqual([item['call_id'] for item in mappings], ['local-test'])

    def test_same_upstream_keeps_multiple_call_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'provider_model_overrides.json'
            with patch.object(auth, 'MODEL_MAPPING_OVERRIDES_FILE', path):
                auth.set_provider_model_override('codex', 'gpt-test', 'local-a', 'codex', 'gpt-test')
                auth.set_provider_model_override('codex', 'gpt-test', 'local-b', 'codex', 'gpt-test')
                auth.set_provider_model_override('codex', 'gpt-test', 'local-a', 'codex', 'gpt-test')

                overrides = auth._load_model_mapping_overrides()
                mappings = auth.resolve_provider_mappings('codex', 'gpt-test', 'gpt-test', overrides=overrides)
                rows = [
                    row for item in auth.get_configured_provider_models()
                    for row in item.get('rows', [])
                    if row.get('lookup_upstream_id') == 'gpt-test'
                ]
                alias_block = auth.build_oauth_model_alias_block(['codex'])

            self.assertEqual([item['call_id'] for item in mappings], ['local-b', 'local-a'])
            self.assertEqual(sorted(row.get('call_id') for row in rows), ['local-a', 'local-b'])
            self.assertEqual(alias_block.count('alias: "local-a"'), 1)
            self.assertEqual(alias_block.count('alias: "local-b"'), 1)

    def test_delete_specific_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'provider_model_overrides.json'
            with patch.object(auth, 'MODEL_MAPPING_OVERRIDES_FILE', path):
                # Set two mappings for the same upstream
                auth.set_provider_model_override('codex', 'gpt-test', 'local-a', 'codex', 'gpt-test')
                auth.set_provider_model_override('codex', 'gpt-test', 'local-b', 'codex', 'gpt-test')
                
                # Delete only local-a
                auth.delete_provider_model_override('codex', 'gpt-test', 'local-a')
                
                overrides = auth._load_model_mapping_overrides()
                mappings = auth.resolve_provider_mappings('codex', 'gpt-test', 'gpt-test', overrides=overrides)
                
            # Verify that only local-b remains
            self.assertEqual([item['call_id'] for item in mappings], ['local-b'])


if __name__ == '__main__':
    unittest.main()

