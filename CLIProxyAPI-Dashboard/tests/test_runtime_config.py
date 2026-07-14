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
            self.assertIn(str(active_auth_dir).replace('\\', '/'), runtime_text)


if __name__ == '__main__':
    unittest.main()
