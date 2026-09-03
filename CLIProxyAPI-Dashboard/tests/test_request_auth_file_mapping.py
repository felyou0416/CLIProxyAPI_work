import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RequestAuthFileMappingTests(unittest.TestCase):
    def test_api_identity_supports_common_auth_file_schemas(self):
        from backend.request_metrics import parsing

        with tempfile.TemporaryDirectory() as tmp:
            auth_dir = Path(tmp)
            (auth_dir / 'provider-a').mkdir()
            (auth_dir / 'provider-b').mkdir()
            (auth_dir / 'provider-c').mkdir()
            (auth_dir / 'provider-a' / 'first.json').write_text(
                json.dumps({'content': {
                    'type': 'api_key',
                    'api_key': 'key-a',
                    'base_url': 'https://one.example/v1/',
                }}),
                encoding='utf-8',
            )
            (auth_dir / 'provider-b' / 'second.json').write_text(
                json.dumps({
                    'api_key': 'key-b',
                    'base-url': 'https://two.example/v1',
                }),
                encoding='utf-8',
            )
            (auth_dir / 'provider-c' / 'third.json').write_text(
                json.dumps({
                    'metadata': {'api_key': 'key-c', 'base_url': 'https://three.example/v1'},
                }),
                encoding='utf-8',
            )
            (auth_dir / 'provider-c' / 'fourth.json').write_text(
                json.dumps({
                    'tokens': {'api_key': 'key-d'},
                    'base_url': 'https://four.example/v1',
                }),
                encoding='utf-8',
            )

            with patch.object(parsing, 'AUTH_DIR', auth_dir):
                mapping = parsing._build_api_key_to_filename_map()

        self.assertEqual(mapping[('key-a', 'https://one.example/v1')], 'provider-a/first.json')
        self.assertEqual(mapping[('key-b', 'https://two.example/v1')], 'provider-b/second.json')
        self.assertEqual(mapping[('key-c', 'https://three.example/v1')], 'provider-c/third.json')
        self.assertEqual(mapping[('key-d', 'https://four.example/v1')], 'provider-c/fourth.json')

    def test_key_only_identity_is_not_mapped(self):
        from backend.request_metrics import parsing

        with tempfile.TemporaryDirectory() as tmp:
            auth_dir = Path(tmp)
            auth_dir.mkdir(exist_ok=True)
            (auth_dir / 'key-only.json').write_text(
                json.dumps({'content': {'api_key': 'key-only'}}),
                encoding='utf-8',
            )

            with patch.object(parsing, 'AUTH_DIR', auth_dir):
                mapping = parsing._build_api_key_to_filename_map()

        self.assertNotIn(('key-only', ''), mapping)

    def test_duplicate_api_identity_is_not_assigned_to_any_file(self):
        from backend.request_metrics import parsing

        with tempfile.TemporaryDirectory() as tmp:
            auth_dir = Path(tmp)
            for provider in ('provider-a', 'provider-b'):
                directory = auth_dir / provider
                directory.mkdir()
                (directory / 'same.json').write_text(
                    json.dumps({'content': {
                        'api_key': 'same-key',
                        'base_url': 'https://same.example/v1',
                    }}),
                    encoding='utf-8',
                )

            with patch.object(parsing, 'AUTH_DIR', auth_dir):
                mapping = parsing._build_api_key_to_filename_map()

        self.assertNotIn(('same-key', 'https://same.example/v1'), mapping)

    def test_auth_index_rebuilds_when_source_auth_file_changes(self):
        from backend.request_metrics import parsing

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth_dir = root / 'auth'
            auth_dir.mkdir()
            auth_file = auth_dir / 'provider.json'
            auth_file.write_text(json.dumps({
                'content': {
                    'api_key': 'cached-key',
                    'base_url': 'https://runtime.example/v1',
                },
            }), encoding='utf-8')
            runtime_config = root / 'runtime.yaml'
            runtime_config.write_text(
                'openai-compatibility:\n'
                '  - name: runtime\n'
                '    base-url: https://runtime.example/v1\n'
                '    api-key-entries:\n'
                '      - api-key: cached-key\n',
                encoding='utf-8',
            )

            with patch.object(parsing, 'AUTH_DIR', auth_dir), \
                    patch.object(parsing, 'RUNTIME_CONFIG', runtime_config), \
                    patch.object(parsing, '_AUTH_ID_INDEX', {}), \
                    patch.object(parsing, '_AUTH_ID_INDEX_MTIME', 0.0), \
                    patch.object(parsing, '_AUTH_ID_INDEX_AUTH_SIGNATURE', None), \
                    patch.object(parsing, '_AUTH_ID_INDEX_STAT_CHECKED_AT', 0.0), \
                    patch.object(parsing, '_AUTH_ID_INDEX_STAT_THROTTLE_SECONDS', 0.0):
                first = parsing._get_auth_id_index()
                auth_id = next(iter(first))
                self.assertEqual(first[auth_id]['auth_file'], 'provider.json')

                auth_file.write_text(json.dumps({
                    'content': {
                        'api_key': 'changed-key',
                        'base_url': 'https://runtime.example/v1',
                    },
                }), encoding='utf-8')

                second = parsing._get_auth_id_index()
                self.assertEqual(second[auth_id]['auth_file'], '')


if __name__ == '__main__':
    unittest.main()
