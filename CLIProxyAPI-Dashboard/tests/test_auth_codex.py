import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import auth


class CodexAccessOnlyAuthTests(unittest.TestCase):
    def test_xai_profile_array_is_unwrapped_and_requires_access_token(self):
        payload = {
            'auth_mode': 'oauth',
            'has_grok_code_access': True,
            'email': 'cqj@example.com',
            'team_id': 'team-1',
            'access_token': '',
        }
        auth_kind = auth._detect_auth_payload_kind(payload)
        self.assertEqual(auth_kind, 'xai_oauth_profile')
        self.assertEqual(auth.detect_provider(payload, 'accounts.json'), 'xai')
        self.assertIsNone(auth._normalize_runtime_oauth_payload(payload, 'xai', auth_kind))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'accounts.json'
            path.write_text(json.dumps([payload]), encoding='utf-8')
            unwrapped = auth._read_auth_payload(path)
        self.assertEqual(unwrapped['email'], 'cqj@example.com')

    def test_xai_profile_with_access_token_normalizes_to_cpa_auth(self):
        payload = {
            'auth_mode': 'oauth',
            'has_grok_code_access': True,
            'email': 'cqj@example.com',
            'access_token': 'xai-access',
            'refresh_token': 'xai-refresh',
        }
        auth_kind = auth._detect_auth_payload_kind(payload)
        normalized = auth._normalize_runtime_oauth_payload(payload, 'xai', auth_kind)
        self.assertEqual(normalized['type'], 'xai')
        self.assertEqual(normalized['access_token'], 'xai-access')
        self.assertEqual(normalized['refresh_token'], 'xai-refresh')
        self.assertEqual(normalized['base_url'], 'https://api.x.ai/v1')

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

    def test_delete_specific_cross_provider_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'provider_model_overrides.json'
            with patch.object(auth, 'MODEL_MAPPING_OVERRIDES_FILE', path):
                auth.set_provider_model_override('codex', 'gpt-test', 'local-a', 'openai-compatibility', 'gpt-test')
                auth.set_provider_model_override('codex', 'gpt-test', 'local-b', 'codex', 'gpt-test')

                auth.delete_provider_model_override('codex', 'gpt-test', 'local-a')

                overrides = auth._load_model_mapping_overrides()
                mappings = auth.resolve_provider_mappings('codex', 'gpt-test', 'gpt-test', overrides=overrides)

            self.assertEqual([item['call_id'] for item in mappings], ['local-b'])

    def test_xai_oauth_aliases_are_publicly_prefixed(self):
        with patch.object(auth, 'collect_provider_model_aliases', return_value={
            'xai': [('grok-build-0.1', 'grok-build-0.1')],
        }), patch.object(auth, '_load_model_mapping_overrides', return_value={}), \
             patch.object(auth, '_aggregate_alias_id_set', return_value=set()), \
             patch.object(auth, '_load_disabled_aggregate_aliases', return_value=set()), \
             patch.object(auth, '_load_provider_model_test_results', return_value={}), \
             patch.object(auth, '_current_route_strategy', return_value={'enabled': False, 'aggregate_only': False}), \
             patch.object(auth, 'resolve_provider_mappings', return_value=[{
                 'upstream_id': 'grok-build-0.1',
                 'target_provider': 'xai',
                 'call_id': 'xai-grok-build-0.1',
             }]), patch.object(auth, 'derive_global_aggregate_aliases', return_value=[]), \
             patch.object(auth, 'get_custom_aggregate_aliases_for_model', return_value=[]):
            block = auth.build_oauth_model_alias_block(['xai'])

        self.assertIn('alias: "xai-grok-build-0.1"', block)
        self.assertNotIn('alias: "grok-build-0.1"', block)
        self.assertIn('fork: false', block)

    def test_deleting_last_specific_mapping_hides_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'provider_model_overrides.json'
            with patch.object(auth, 'MODEL_MAPPING_OVERRIDES_FILE', path):
                auth.set_provider_model_override('codex', 'gpt-test', 'local-a', 'codex', 'gpt-test')

                auth.delete_provider_model_override('codex', 'gpt-test', 'local-a')

                overrides = auth._load_model_mapping_overrides()
                mappings = auth.resolve_provider_mappings('codex', 'gpt-test', 'gpt-test', overrides=overrides)

            self.assertEqual(len(mappings), 1)
            self.assertTrue(mappings[0]['deleted'])

    def test_setting_same_call_id_updates_current_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'provider_model_overrides.json'
            with patch.object(auth, 'MODEL_MAPPING_OVERRIDES_FILE', path):
                auth.set_provider_model_override('codex', 'gpt-test', 'local-a', 'codex', 'gpt-test')
                auth.set_provider_model_override('codex', 'gpt-test', 'local-a', 'openai-compatibility', 'gpt-4o')

                overrides = auth._load_model_mapping_overrides()
                entries = auth.iter_model_mapping_entries(overrides, 'codex', 'gpt-test')
                mappings = auth.resolve_provider_mappings('codex', 'gpt-test', 'gpt-test', overrides=overrides)

            self.assertEqual(len(entries), 1)
            self.assertEqual(mappings[0]['target_provider'], 'openai-compatibility')
            self.assertEqual(mappings[0]['upstream_id'], 'gpt-4o')
            self.assertEqual(mappings[0]['call_id'], 'local-a')


if __name__ == '__main__':
    unittest.main()
