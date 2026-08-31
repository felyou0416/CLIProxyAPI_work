import unittest
import tempfile
import json
import shutil
from pathlib import Path
from unittest.mock import patch

from backend.model_pool import save_model_pools, load_model_pools, get_model_pool_manual_entries, remap_local_pool_proxy_urls
from backend.auth import build_openai_compatibility_block, get_configured_provider_models, _extract_payload_models, _extract_manual_api_config, rewrite_openai_compatibility

class TestModelPoolStorage(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.auth_dir = Path(self.tmp_dir) / 'auth'
        self.model_pools_dir = self.auth_dir / 'model_pools'
        self.index_file = Path(self.tmp_dir) / 'model_pools.json'

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_storage_auth_folder_structure(self):
        sample_pools = [
            {
                "id": "pool-test-1",
                "provider": "pool-provider-custom",
                "call_id": "custom-gpt4-pool",
                "enabled": True,
                "nodes": [
                    {
                        "id": "node-1",
                        "base_url": "https://api.openai-proxy1.com/v1",
                        "api_key": "sk-key1",
                        "upstream_id": "gpt-4o",
                        "weight": 2,
                        "enabled": True
                    },
                    {
                        "id": "node-2",
                        "base_url": "https://api.openai-proxy2.com/v1",
                        "api_key": "sk-key2",
                        "upstream_id": "gpt-4o-mini",
                        "weight": 1,
                        "enabled": True
                    }
                ]
            }
        ]

        with patch("backend.model_pool.MODEL_POOLS_AUTH_DIR", self.model_pools_dir), \
             patch("backend.model_pool.MODEL_POOLS_FILE", self.index_file):

            success = save_model_pools(sample_pools)
            self.assertTrue(success)

            # Check that storage/auth/model_pools/custom-gpt4-pool exists
            pool_folder = self.model_pools_dir / "custom-gpt4-pool"
            self.assertTrue(pool_folder.exists())
            self.assertTrue(pool_folder.is_dir())

            # Auth storage contains reference manifests only.
            manifest_path = pool_folder / "preset_1.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            self.assertEqual(manifest['metadata']['file_schema'], 'cliproxyapi-model-pool-ref-v2')
            self.assertNotIn('base_url', json.dumps(manifest))
            self.assertNotIn('api_key', json.dumps(manifest))
            self.assertEqual(manifest['references']['node_refs'][0]['node_ref'], 'node-1')

            # Load back and verify
            loaded = load_model_pools()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["call_id"], "custom-gpt4-pool")
            self.assertEqual(len(loaded[0]["nodes"]), 2)

    def test_extract_payload_models_fallback_to_folder_name(self):
        payload_without_model = {
            "type": "api_key",
            "provider": "pool-provider-custom",
            "base_url": "https://api.openai-proxy1.com/v1",
            "api_key": "sk-key1"
        }
        node_file_path = self.model_pools_dir / "gpt-4o-custom" / "node_1.json"
        extracted = _extract_payload_models(payload_without_model, path=node_file_path)
        self.assertIn("gpt-4o-custom", extracted)

    def test_archived_pool_routes_are_omitted(self):
        entries = [{
            'provider': 'manual-provider',
            'base_url': 'https://manual.example/v1',
            'api_key': 'manual-key',
            'models': ['manual-model'],
        }]
        pool_entries = [{
            'provider': 'pool-provider',
            'base_url': 'https://pool.example/v1',
            'api_key': 'pool-key',
            'models': ['pool-model'],
        }]
        with patch('backend.auth.load_state', return_value={'model_pool_archived': True}), \
             patch('backend.model_pool.get_model_pool_manual_entries', return_value=pool_entries) as get_pool_entries:
            rendered = rewrite_openai_compatibility('', entries)

        self.assertIn('manual-provider', rendered)
        self.assertNotIn('pool-provider', rendered)
        get_pool_entries.assert_not_called()

    def test_unarchived_pool_routes_are_included(self):
        pool_entries = [{
            'provider': 'pool-provider',
            'base_url': 'https://pool.example/v1',
            'api_key': 'pool-key',
            'models': ['pool-model'],
        }]
        with patch('backend.auth.load_state', return_value={'model_pool_archived': False}), \
             patch('backend.model_pool.get_model_pool_manual_entries', return_value=pool_entries):
            rendered = rewrite_openai_compatibility('', [])

        self.assertIn('pool-provider', rendered)

    def test_remap_local_pool_proxy_urls_preserves_direct_and_external(self):
        sample_pools = [{
            'id': 'pool-test-1',
            'provider': 'pool-provider-custom',
            'call_id': 'custom-pool',
            'nodes': [
                {'id': 'local', 'base_url': 'https://local.example/v1', 'api_key': 'one', 'upstream_id': 'a', 'proxy_url': 'http://127.0.0.1:7890'},
                {'id': 'direct', 'base_url': 'https://direct.example/v1', 'api_key': 'two', 'upstream_id': 'b', 'proxy_url': 'direct'},
                {'id': 'external', 'base_url': 'https://external.example/v1', 'api_key': 'three', 'upstream_id': 'c', 'proxy_url': 'http://proxy.example:8080'},
            ],
        }]
        with patch('backend.model_pool.load_model_pools', return_value=sample_pools), \
             patch('backend.model_pool.save_model_pools', return_value=True) as save:
            result = remap_local_pool_proxy_urls('http://127.0.0.1:10090')

        self.assertTrue(result['ok'])
        self.assertEqual(result['changed_nodes'], 1)
        nodes = save.call_args.args[0][0]['nodes']
        self.assertEqual(nodes[0]['proxy_url'], 'http://127.0.0.1:10090')
        self.assertEqual(nodes[1]['proxy_url'], 'direct')
        self.assertEqual(nodes[2]['proxy_url'], 'http://proxy.example:8080')

    def test_get_model_pool_manual_entries_building(self):
        sample_pools = [
            {
                "id": "pool-test-1",
                "provider": "pool-provider-custom",
                "call_id": "custom-gpt4-pool",
                "enabled": True,
                "nodes": [
                    {
                        "id": "node-1",
                        "base_url": "https://api.openai-proxy1.com/v1",
                        "api_key": "sk-key1",
                        "upstream_id": "gpt-4o",
                        "weight": 5,
                        "enabled": True
                    }
                ]
            }
        ]

        with patch("backend.model_pool.load_model_pools", return_value=sample_pools):
            entries = get_model_pool_manual_entries()
            self.assertEqual(len(entries), 2)
            self.assertEqual({entry["direct_alias"] for entry in entries}, {"custom-gpt4-pool", "gpt-4o"})
            self.assertEqual(entries[0]["provider"], "pool-provider-custom")

            yaml_block = build_openai_compatibility_block(entries)
            self.assertIn('name: "pool-provider-custom"', yaml_block)
            self.assertIn('base-url: "https://api.openai-proxy1.com/v1"', yaml_block)
            self.assertIn('api-key: "sk-key1"', yaml_block)
            self.assertIn('weight: 5', yaml_block)
            self.assertIn('alias: "custom-gpt4-pool"', yaml_block)

    def test_openai_compat_gpt56_models_declare_extended_thinking_levels(self):
        entries = [{
            'provider': 'custom-openai',
            'base_url': 'https://example.invalid/v1',
            'api_key': 'test-key',
            'models': [
                'gpt-5.6-sol',
                'gpt-5.6-terra(max)',
                'openai/gpt-5.6-luna',
            ],
        }]

        with patch('backend.auth._load_model_mapping_overrides', return_value={}):
            rendered = build_openai_compatibility_block(entries)

        expected = 'levels: ["low", "medium", "high", "xhigh", "max"]'
        self.assertEqual(rendered.count(expected), 3)
        self.assertIn('name: "gpt-5.6-sol"', rendered)
        self.assertIn('name: "gpt-5.6-terra(max)"', rendered)
        self.assertIn('name: "openai/gpt-5.6-luna"', rendered)

    def test_openai_compat_unknown_models_keep_core_default_capabilities(self):
        entries = [{
            'provider': 'custom-openai',
            'base_url': 'https://example.invalid/v1',
            'api_key': 'test-key',
            'models': ['gpt-5.5', 'custom-reasoning-model'],
        }]

        with patch('backend.auth._load_model_mapping_overrides', return_value={}):
            rendered = build_openai_compatibility_block(entries)

        self.assertNotIn('thinking:', rendered)
        self.assertIn('name: "gpt-5.5"', rendered)
        self.assertIn('name: "custom-reasoning-model"', rendered)

if __name__ == "__main__":
    unittest.main()
