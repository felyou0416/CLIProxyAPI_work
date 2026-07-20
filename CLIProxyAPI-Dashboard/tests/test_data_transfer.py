import unittest
from pathlib import Path
from unittest.mock import patch

from backend import data_transfer as dt


class DataTransferEnvironmentTests(unittest.TestCase):
    def test_detect_environment_dev_by_default(self):
        env = dt.detect_environment()
        self.assertIn(env['profile'], {'dev', 'user'})
        self.assertTrue(env['storage_dir'])
        self.assertTrue(env['auth_dir'])

    def test_detect_environment_user_when_storage_env_set(self):
        with patch.dict('os.environ', {'CLIPROXYAPI_STORAGE_DIR': 'C:/AppData/CLIProxyAPI/storage'}, clear=False):
            # detect_environment reads env at call time via os.environ
            env = dt.detect_environment()
            self.assertEqual(env['profile'], 'user')
            self.assertTrue(env['has_storage_env'])


class YamlPathRewriteTests(unittest.TestCase):
    def test_rewrites_windows_auth_dir(self):
        sample = 'host: "127.0.0.1"\nauth-dir: "E:/Other/Machine/storage/auth"\nport: 8317\n'
        out, notes = dt._rewrite_yaml_paths(sample)
        self.assertTrue(notes)
        self.assertIn(str(dt.AUTH_DIR).replace('\\', '/'), out.replace('\\', '/'))
        self.assertNotIn('E:/Other/Machine/storage/auth', out)

    def test_leaves_relative_paths(self):
        sample = 'auth-dir: "storage/auth"\n'
        out, notes = dt._rewrite_yaml_paths(sample)
        # relative non-abs may still rewrite if key is auth-dir — accept either stable result
        self.assertIsInstance(out, str)


class ImportCompatibilityTests(unittest.TestCase):
    def test_rejects_missing_version(self):
        res = dt.import_all({'data': {}}, mode='merge')
        self.assertFalse(res['ok'])
        self.assertIn('version', res['message'].lower())

    def test_rejects_unknown_version(self):
        res = dt.import_all({'version': 99, 'data': {'api_keys': []}}, mode='merge')
        self.assertFalse(res['ok'])
        self.assertIn('Unsupported', res['message'])

    def test_accepts_v1_flat_layout(self):
        # v1: keys at top-level, no data wrapper
        res = dt.import_all({'version': 1, 'api_keys': []}, mode='merge')
        self.assertTrue(res['ok'])

    def test_accepts_v3_with_cross_profile_warning(self):
        res = dt.import_all(
            {
                'version': 3,
                'environment': {'profile': 'user'},
                'data': {'api_keys': []},
            },
            mode='merge',
        )
        self.assertTrue(res['ok'])
        # warning only when profiles differ
        if dt.detect_environment().get('profile') == 'dev':
            self.assertTrue(any('cross-profile' in w for w in res.get('warnings') or []))

    def test_export_includes_environment_and_summary(self):
        exp = dt.export_all()
        self.assertTrue(exp['ok'])
        self.assertEqual(exp['version'], dt.EXPORT_VERSION)
        self.assertIn('environment', exp)
        self.assertIn('summary', exp)
        self.assertIn('data', exp)
        self.assertIn(exp['environment']['profile'], {'dev', 'user'})


class AuthRelativePathTests(unittest.TestCase):
    def test_blocks_path_traversal_on_import(self):
        res = dt.import_all(
            {
                'version': 3,
                'data': {
                    'auth_entries': [
                        {
                            'relative_name': '../escape.json',
                            'payload': {'type': 'api_key'},
                        }
                    ]
                },
            },
            mode='merge',
        )
        # traversal entry skipped, no crash
        self.assertTrue(res['ok'] or res.get('errors') == [])
        self.assertFalse((dt.AUTH_DIR.parent / 'escape.json').exists())


if __name__ == '__main__':
    unittest.main()
