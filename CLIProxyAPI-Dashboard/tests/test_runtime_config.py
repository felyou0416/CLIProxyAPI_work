import pathlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.auth as auth


class RuntimeCoreOptionsTests(unittest.TestCase):
    def test_runtime_options_are_rendered_from_dashboard_state(self):
        rendered = auth.rewrite_core_runtime_options(
            'host: "127.0.0.1"\n'
            'codex:\n'
            '  identity-confuse: false\n'
            '  live-media-relay:\n'
            '    enabled: true\n'
            '    max-sessions: 12\n', {
            'force_model_prefix': True, 'passthrough_headers': True, 'request_retry': 5,
            'max_retry_credentials': 2, 'max_retry_interval': 45, 'save_cooldown_status': True,
            'transient_error_cooldown_seconds': -1, 'video_result_auth_cache_ttl': '4h',
            'logging_to_file': True, 'logs_max_total_size_mb': 512, 'error_logs_max_files': 20,
            'usage_statistics_enabled': True, 'usage_queue_retention_seconds': 120,
            'nonstream_keepalive_interval': 10, 'quota_switch_project': False,
            'quota_switch_preview_model': True, 'quota_antigravity_credits': False,
            'streaming_keepalive_seconds': 15, 'streaming_bootstrap_retries': 2,
            'codex_identity_confuse': True, 'codex_disable_cloaking': True,
            'codex_optimize_multi_agent_v2': True,
            'claude_code_disable_cloaking_model_list': True,
            'xai_inject_x_search': True,
        })
        self.assertIn('force-model-prefix: true', rendered)
        self.assertIn('request-retry: 5', rendered)
        self.assertIn('video-result-auth-cache-ttl: "4h"', rendered)
        self.assertIn('logging-to-file: true', rendered)
        self.assertIn('usage-statistics-enabled: true', rendered)
        self.assertIn('quota-exceeded:\n  switch-project: false', rendered)
        self.assertIn('streaming:\n  keepalive-seconds: 15\n  bootstrap-retries: 2', rendered)
        self.assertIn('codex:\n  identity-confuse: true', rendered)
        self.assertIn('  disable-codex-cloaking: true', rendered)
        self.assertIn('  optimize-multi-agent-v2: true', rendered)
        self.assertIn('  live-media-relay:\n    enabled: true\n    max-sessions: 12', rendered)
        self.assertIn('claude-code:\n  disable-cloaking-model-list: true', rendered)
        self.assertIn('xai:\n  inject-x-search: true', rendered)
        self.assertEqual(rendered.count('\ncodex:\n'), 1)

    def test_weighted_round_robin_is_rendered(self):
        rendered = auth.rewrite_routing_config('', strategy='weighted-round-robin')
        self.assertIn('strategy: "weighted-round-robin"', rendered)

    def test_auth_pool_sync_rebuilds_only_after_a_change(self):
        signature = (('codex/account.json', 1, 10),)
        with patch.object(auth, '_auth_pool_signature', return_value=signature), \
             patch.object(auth, 'rebuild_runtime_config_from_state', return_value={'rebuilt': True, 'copied_auth_count': 1}) as rebuild:
            first = auth.sync_auth_pool_if_changed(None)
            second = auth.sync_auth_pool_if_changed(first['signature'])

        self.assertTrue(first['changed'])
        self.assertFalse(second['changed'])
        rebuild.assert_called_once_with()

    def test_empty_auth_pool_removes_stale_runtime_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            pool = root / 'pool'
            active = root / 'active'
            pool.mkdir()
            active.mkdir()
            stale = active / 'stale.json'
            stale.write_text('{"type":"codex"}', encoding='utf-8')
            with patch.object(auth, 'POOL_AUTH_DIR', pool), patch.object(auth, 'ACTIVE_AUTH_DIR', active):
                result = auth.rebuild_runtime_config_from_state({})

        self.assertEqual(result['reason'], 'no_auth_files')
        self.assertEqual(result['removed_active_auth_count'], 1)
        self.assertFalse(stale.exists())

    def test_all_disabled_auth_files_remove_stale_runtime_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            pool_auth_dir = root / 'auth'
            active_auth_dir = root / 'runtime-auth'
            provider_dir = pool_auth_dir / 'codex'
            provider_dir.mkdir(parents=True)
            active_auth_dir.mkdir(parents=True)
            (provider_dir / 'disabled.json').write_text(json.dumps({'disabled': True}), encoding='utf-8')
            stale = active_auth_dir / 'stale.json'
            stale.write_text('{"type":"codex"}', encoding='utf-8')

            with patch.object(auth, 'POOL_AUTH_DIR', pool_auth_dir), \
                 patch.object(auth, 'ACTIVE_AUTH_DIR', active_auth_dir):
                result = auth.rebuild_runtime_config_from_state({})

            self.assertEqual(result['reason'], 'no_auth_files')
            self.assertFalse(stale.exists())

    def test_auth_item_redacts_api_key_from_dashboard_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth_path = pathlib.Path(tmp) / 'key.json'
            auth_path.write_text(json.dumps({
                'content': {
                    'type': 'api_key',
                    'provider': 'test-provider',
                    'api_key': 'secret-api-key-value',
                },
            }), encoding='utf-8')
            item = auth.build_auth_item('test-provider', auth_path)

        self.assertNotIn('apiKey', item)
        self.assertEqual(item['apiKeyMasked'], 'secret...alue')

    def test_passthrough_image_mode_is_supported(self):
        rendered = auth.rewrite_disable_image_generation('disable-image-generation: false\n', 'passthrough')
        self.assertIn('disable-image-generation: "passthrough"', rendered)


class RuntimeConfigRequestLogTests(unittest.TestCase):
    def test_build_runtime_config_enables_request_log_for_observability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            base_config = root / 'base-config.yaml'
            runtime_config = root / 'runtime.yaml'
            pool_auth_dir = root / 'auth'
            active_auth_dir = root / 'runtime-auth'
            provider_dir = pool_auth_dir / 'test-provider'
            provider_dir.mkdir(parents=True)
            (provider_dir / 'test.json').write_text('{"api_key":"test"}', encoding='utf-8')
            base_config.write_text('host: "127.0.0.1"\nrequest-log: false\napi-keys:\n  - "old"\n', encoding='utf-8')

            with patch.object(auth, 'BASE_CONFIG', base_config), \
                 patch.object(auth, 'RUNTIME_CONFIG', runtime_config), \
                 patch.object(auth, 'POOL_AUTH_DIR', pool_auth_dir), \
                 patch.object(auth, 'ACTIVE_AUTH_DIR', active_auth_dir), \
                 patch.object(auth, 'iter_auth_source_dirs', return_value=[('test-provider', provider_dir)]), \
                 patch.object(auth, 'detect_provider', return_value='test-provider'), \
                 patch.object(auth, 'rewrite_oauth_model_aliases', side_effect=lambda text, providers, auth_refs=None: text), \
                 patch.object(auth, 'rewrite_claude_api_key', side_effect=lambda text, entries: text), \
                 patch.object(auth, 'rewrite_openai_compatibility', side_effect=lambda text, entries: text), \
                 patch.object(auth, '_runtime_config_validation_issues', return_value=[]):
                auth.build_runtime_config(bind_host='127.0.0.1', access_api_keys=['cliproxyapi'], state={})

            runtime_text = runtime_config.read_text(encoding='utf-8')
            self.assertIn('request-log: true', runtime_text)
            self.assertNotIn('request-log: false', runtime_text)

    def test_codex_oauth_is_normalized_into_flat_runtime_auth_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            base_config = root / 'base-config.yaml'
            runtime_config = root / 'runtime.yaml'
            pool_auth_dir = root / 'auth'
            active_auth_dir = root / 'runtime-auth'
            provider_dir = pool_auth_dir / 'codex'
            provider_dir.mkdir(parents=True)
            (provider_dir / 'account.json').write_text(json.dumps({
                'metadata': {'email': 'user@example.com', 'provider': 'openai-codex'},
                'content': {
                    'type': 'oauth',
                    'provider': 'openai-codex',
                    'access': 'access-token',
                    'refresh': 'refresh-token',
                    'accountId': 'acct_123',
                },
            }), encoding='utf-8')
            base_config.write_text('host: "127.0.0.1"\nauth-dir: "old"\n', encoding='utf-8')

            with patch.object(auth, 'BASE_CONFIG', base_config), \
                 patch.object(auth, 'RUNTIME_CONFIG', runtime_config), \
                 patch.object(auth, 'POOL_AUTH_DIR', pool_auth_dir), \
                 patch.object(auth, 'ACTIVE_AUTH_DIR', active_auth_dir), \
                 patch.object(auth, 'rewrite_oauth_model_aliases', side_effect=lambda text, providers, auth_refs=None: text), \
                 patch.object(auth, 'rewrite_claude_api_key', side_effect=lambda text, entries: text), \
                 patch.object(auth, 'rewrite_openai_compatibility', side_effect=lambda text, entries: text), \
                 patch.object(auth, '_runtime_config_validation_issues', return_value=[]):
                copied = auth.build_runtime_config(bind_host='127.0.0.1', access_api_keys=['cliproxyapi'], state={})

            self.assertEqual(len(copied), 1)
            normalized = json.loads(copied[0].read_text(encoding='utf-8'))
            self.assertEqual(normalized['type'], 'codex')
            self.assertEqual(normalized['provider'], 'codex')
            self.assertEqual(normalized['access_token'], 'access-token')
            runtime_text = runtime_config.read_text(encoding='utf-8')
            self.assertIn(pathlib.Path(active_auth_dir).resolve().as_posix(), runtime_text)

    def test_disabled_oauth_is_not_copied_to_runtime_auth_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            base_config = root / 'base-config.yaml'
            runtime_config = root / 'runtime.yaml'
            pool_auth_dir = root / 'auth'
            active_auth_dir = root / 'runtime-auth'
            provider_dir = pool_auth_dir / 'codex'
            provider_dir.mkdir(parents=True)
            oauth_payload = {
                'metadata': {'email': 'disabled@example.com', 'provider': 'openai-codex'},
                'content': {
                    'type': 'oauth',
                    'provider': 'openai-codex',
                    'access': 'disabled-access',
                    'refresh': 'disabled-refresh',
                    'accountId': 'disabled-account',
                },
                'disabled': True,
            }
            enabled_payload = {
                'metadata': {'email': 'enabled@example.com', 'provider': 'openai-codex'},
                'content': {
                    'type': 'oauth',
                    'provider': 'openai-codex',
                    'access': 'enabled-access',
                    'refresh': 'enabled-refresh',
                    'accountId': 'enabled-account',
                },
            }
            (provider_dir / 'disabled.json').write_text(json.dumps(oauth_payload), encoding='utf-8')
            (provider_dir / 'enabled.json').write_text(json.dumps(enabled_payload), encoding='utf-8')
            base_config.write_text('host: "127.0.0.1"\nauth-dir: "old"\n', encoding='utf-8')

            with patch.object(auth, 'BASE_CONFIG', base_config), \
                 patch.object(auth, 'RUNTIME_CONFIG', runtime_config), \
                 patch.object(auth, 'POOL_AUTH_DIR', pool_auth_dir), \
                 patch.object(auth, 'ACTIVE_AUTH_DIR', active_auth_dir), \
                 patch.object(auth, 'rewrite_oauth_model_aliases', side_effect=lambda text, providers, auth_refs=None: text), \
                 patch.object(auth, 'rewrite_claude_api_key', side_effect=lambda text, entries: text), \
                 patch.object(auth, 'rewrite_openai_compatibility', side_effect=lambda text, entries: text), \
                 patch.object(auth, '_runtime_config_validation_issues', return_value=[]):
                copied = auth.build_runtime_config(bind_host='127.0.0.1', access_api_keys=['cliproxyapi'], state={})

            self.assertEqual(len(copied), 1)
            self.assertEqual(json.loads(copied[0].read_text(encoding='utf-8'))['access_token'], 'enabled-access')
            self.assertEqual({path.name for path in active_auth_dir.glob('*.json')}, {copied[0].name})

    def test_disabled_files_are_excluded_from_provider_and_model_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            pool_auth_dir = root / 'auth'
            provider_dir = pool_auth_dir / 'disabled-provider'
            provider_dir.mkdir(parents=True)
            (provider_dir / 'disabled.json').write_text(json.dumps({
                'disabled': True,
                'content': {
                    'type': 'oauth',
                    'provider': 'disabled-provider',
                    'access': 'access-token',
                    'refresh': 'refresh-token',
                    'models': ['disabled-model'],
                },
            }), encoding='utf-8')

            with patch.object(auth, 'POOL_AUTH_DIR', pool_auth_dir), \
                 patch.object(auth, 'iter_auth_source_dirs', return_value=[('disabled-provider', provider_dir)]), \
                 patch.object(auth, '_load_model_mapping_overrides', return_value={}):
                self.assertEqual(auth.collect_detected_providers(), [])
                aliases = auth.collect_provider_model_aliases()

            self.assertNotIn('disabled-provider', aliases)

    def test_disabled_manual_api_key_is_not_added_to_compatibility_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            base_config = root / 'base-config.yaml'
            runtime_config = root / 'runtime.yaml'
            pool_auth_dir = root / 'auth'
            active_auth_dir = root / 'runtime-auth'
            provider_dir = pool_auth_dir / 'openai'
            provider_dir.mkdir(parents=True)
            for name, provider, api_key, disabled in (
                ('disabled.json', 'disabled-provider', 'disabled-key', True),
                ('enabled.json', 'enabled-provider', 'enabled-key', False),
            ):
                payload = {
                    'disabled': disabled,
                    'content': {
                        'type': 'api_key',
                        'provider': provider,
                        'base_url': 'https://example.invalid/v1',
                        'api_key': api_key,
                        'models': ['test-model'],
                    },
                }
                (provider_dir / name).write_text(json.dumps(payload), encoding='utf-8')
            base_config.write_text('host: "127.0.0.1"\n', encoding='utf-8')
            captured = []

            with patch.object(auth, 'BASE_CONFIG', base_config), \
                 patch.object(auth, 'RUNTIME_CONFIG', runtime_config), \
                 patch.object(auth, 'POOL_AUTH_DIR', pool_auth_dir), \
                 patch.object(auth, 'ACTIVE_AUTH_DIR', active_auth_dir), \
                 patch.object(auth, 'rewrite_oauth_model_aliases', side_effect=lambda text, providers, auth_refs=None: text), \
                 patch.object(auth, 'rewrite_claude_api_key', side_effect=lambda text, entries: text), \
                 patch.object(auth, 'rewrite_openai_compatibility', side_effect=lambda text, entries: captured.extend(entries) or text), \
                 patch.object(auth, '_runtime_config_validation_issues', return_value=[]):
                auth.build_runtime_config(bind_host='127.0.0.1', access_api_keys=['cliproxyapi'], state={})

            self.assertEqual([entry['api_key'] for entry in captured], ['enabled-key'])

class RuntimeConfigLocalPluginTests(unittest.TestCase):
    def test_agnes_media_models_use_media_proxy_group(self):
        entries = [{
            'provider': 'agnes',
            'base_url': 'https://example.invalid/v1',
            'api_key': 'secret-value',
            'models': [
                {'name': 'agnes-2.0-flash', 'alias': 'agnes-agnes-2.0-flash'},
                {'name': 'agnes-image-2.1-flash', 'alias': 'agnes-agnes-image-2.1-flash'},
                {'name': 'agnes-video-v2.0', 'alias': 'agnes-agnes-video-v2.0'},
            ],
        }]
        with patch.object(auth, '_group_manual_entry_models', return_value={
            'agnes': entries[0]['models'],
        }), patch.object(auth, '_load_model_mapping_overrides', return_value={}):
            block = auth.build_openai_compatibility_block(entries)

        self.assertIn('name: "agnes"', block)
        self.assertIn('base-url: "https://example.invalid/v1"', block)
        self.assertIn('name: "agnes-media"', block)
        self.assertIn('base-url: "http://127.0.0.1:8320/v1"', block)
        self.assertIn('alias: "agnes-agnes-image-2.1-flash"', block)
        self.assertIn('image: true', block)

    def test_plugin_config_is_written_as_top_level_block(self):
        rendered = auth.rewrite_local_plugin_config('host: "127.0.0.1"\n')
        self.assertIn('\nplugins:\n', rendered)
        self.assertIn('cliproxy-local:', rendered)
        self.assertIn('media_provider: "openai-compatible-agnes-media"', rendered)

if __name__ == '__main__':
    unittest.main()
