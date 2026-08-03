import unittest
import tempfile
import json
import shutil
from pathlib import Path
from unittest.mock import patch

from backend.model_pool import save_model_pools, load_model_pools, get_model_pool_manual_entries
from backend.auth import build_openai_compatibility_block, get_configured_provider_models, _extract_payload_models, _extract_manual_api_config

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

            # Pool metadata is stored in the index; auth files are standard provider payloads.
            self.assertFalse((pool_folder / "base_config.json").exists())

            # Check node_1.json and node_2.json
            node_1_path = pool_folder / "node_1.json"
            node_2_path = pool_folder / "node_2.json"
            self.assertTrue(node_1_path.exists())
            self.assertTrue(node_2_path.exists())

            node_payload = json.loads(node_1_path.read_text(encoding='utf-8'))
            self.assertEqual(node_payload['content']['type'], 'api_key')
            self.assertEqual(node_payload['content']['provider'], 'pool-provider-custom')
            self.assertEqual(node_payload['content']['models'], ['gpt-4o'])
            self.assertEqual(node_payload['metadata']['call_id'], 'custom-gpt4-pool')
            parsed = _extract_manual_api_config(node_payload, str(node_1_path))
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed['models'], ['gpt-4o'])

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
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["provider"], "pool-provider-custom")

            yaml_block = build_openai_compatibility_block(entries)
            self.assertIn('name: "pool-provider-custom"', yaml_block)
            self.assertIn('base-url: "https://api.openai-proxy1.com/v1"', yaml_block)
            self.assertIn('api-key: "sk-key1"', yaml_block)
            self.assertIn('weight: 5', yaml_block)
            self.assertIn('alias: "custom-gpt4-pool"', yaml_block)

if __name__ == "__main__":
    unittest.main()
