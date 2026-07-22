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
