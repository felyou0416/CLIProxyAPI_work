import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import auth


class LoopbackModelProxyTests(unittest.TestCase):
    def test_is_loopback_base_url(self):
        self.assertTrue(auth._is_loopback_base_url('http://127.0.0.1:8000/v1'))
        self.assertTrue(auth._is_loopback_base_url('http://localhost:8000/v1'))
        self.assertTrue(auth._is_loopback_base_url('http://[::1]:8000/v1'))
        self.assertFalse(auth._is_loopback_base_url('https://api.example.com/v1'))
        self.assertFalse(auth._is_loopback_base_url(''))
        self.assertFalse(auth._is_loopback_base_url('http://10.0.0.5:8000/v1'))

    def test_effective_proxy_forces_direct_for_loopback(self):
        with patch.object(auth, '_model_proxy_url_for_provider', return_value='http://127.0.0.1:7890'):
            with patch.object(auth, '_detect_active_local_proxy', return_value={'ok': False}):
                self.assertEqual(
                    auth._effective_model_proxy_url('grok2api', 'http://127.0.0.1:8000/v1'),
                    'direct',
                )
                self.assertEqual(
                    auth._effective_model_proxy_url('openrouter', 'https://openrouter.ai/api/v1'),
                    'http://127.0.0.1:7890',
                )

    def test_openai_compat_block_writes_direct_for_local_gateway(self):
        entries = [{
            'provider': 'grok2api',
            'base_url': 'http://127.0.0.1:8000/v1',
            'api_key': 'g2a-test-key',
            'models': ['grok-4.5'],
            'headers': {},
        }]
        with patch.object(auth, '_load_model_mapping_overrides', return_value={}):
            with patch.object(auth, '_model_proxy_url_for_provider', return_value='http://127.0.0.1:7890'):
                block = auth.build_openai_compatibility_block(entries)
        self.assertIn('name: "grok2api"', block)
        self.assertIn('base-url: "http://127.0.0.1:8000/v1"', block)
        self.assertIn('proxy-url: "direct"', block)
        self.assertNotIn('proxy-url: "http://127.0.0.1:7890"', block)

    def test_openai_compat_block_keeps_remote_provider_proxy(self):
        entries = [{
            'provider': 'openrouter',
            'base_url': 'https://openrouter.ai/api/v1',
            'api_key': 'sk-or-test',
            'models': ['openrouter/free'],
            'headers': {},
        }]
        with patch.object(auth, '_load_model_mapping_overrides', return_value={}):
            with patch.object(auth, '_model_proxy_url_for_provider', return_value='http://127.0.0.1:7890'):
                with patch.object(auth, '_detect_active_local_proxy', return_value={'ok': False}):
                    block = auth.build_openai_compatibility_block(entries)
        self.assertIn('proxy-url: "http://127.0.0.1:7890"', block)
        self.assertNotIn('proxy-url: "direct"', block)


if __name__ == '__main__':
    unittest.main()
