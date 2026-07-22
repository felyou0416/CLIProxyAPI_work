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
            with patch.object(auth, '_choose_provider_egress_proxy_url', return_value='http://127.0.0.1:7890') as choose:
                self.assertEqual(
                    auth._effective_model_proxy_url('grok2api', 'http://127.0.0.1:8000/v1'),
                    'direct',
                )
                self.assertEqual(
                    auth._effective_model_proxy_url('openrouter', 'https://openrouter.ai/api/v1'),
                    'http://127.0.0.1:7890',
                )
                # loopback must short-circuit before egress comparison
                choose.assert_called_once_with(
                    'openrouter',
                    'https://openrouter.ai/api/v1',
                    prefer_proxy_url='http://127.0.0.1:7890',
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
                with patch.object(auth, '_choose_provider_egress_proxy_url', return_value='http://127.0.0.1:7890'):
                    block = auth.build_openai_compatibility_block(entries)
        self.assertIn('proxy-url: "http://127.0.0.1:7890"', block)
        self.assertNotIn('proxy-url: "direct"', block)

    def test_effective_proxy_uses_homepage_style_choice_for_remote(self):
        with patch.object(auth, '_model_proxy_url_for_provider', return_value='http://127.0.0.1:10090'):
            with patch.object(auth, '_choose_provider_egress_proxy_url', return_value='direct') as choose:
                selected = auth._effective_model_proxy_url('agnes', 'https://apihub.agnes-ai.com/v1')
        self.assertEqual(selected, 'direct')
        choose.assert_called_once()
        args, kwargs = choose.call_args
        self.assertEqual(args[0], 'agnes')
        self.assertEqual(args[1], 'https://apihub.agnes-ai.com/v1')
        self.assertEqual(kwargs.get('prefer_proxy_url'), 'http://127.0.0.1:10090')

    def test_openai_compat_block_can_write_direct_for_remote_when_chosen(self):
        entries = [{
            'provider': 'agnes',
            'base_url': 'https://apihub.agnes-ai.com/v1',
            'api_key': 'sk-agnes-test',
            'models': ['agnes-video-v2.0'],
            'headers': {},
        }]
        with patch.object(auth, '_load_model_mapping_overrides', return_value={}):
            with patch.object(auth, '_model_proxy_url_for_provider', return_value='http://127.0.0.1:10090'):
                with patch.object(auth, '_choose_provider_egress_proxy_url', return_value='direct'):
                    block = auth.build_openai_compatibility_block(entries)
        self.assertIn('name: "agnes"', block)
        self.assertIn('proxy-url: "direct"', block)


if __name__ == '__main__':
    unittest.main()
