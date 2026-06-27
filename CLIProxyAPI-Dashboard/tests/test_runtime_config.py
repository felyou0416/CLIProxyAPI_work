import pathlib
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
            provider_dir = pool_auth_dir / 'test-provider'
            provider_dir.mkdir(parents=True)
            (provider_dir / 'test.json').write_text('{"api_key":"test"}', encoding='utf-8')
            base_config.write_text('host: "127.0.0.1"\nrequest-log: false\napi-keys:\n  - "old"\n', encoding='utf-8')

            with patch.object(auth, 'BASE_CONFIG', base_config), \
                 patch.object(auth, 'RUNTIME_CONFIG', runtime_config), \
                 patch.object(auth, 'POOL_AUTH_DIR', pool_auth_dir), \
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


if __name__ == '__main__':
    unittest.main()
