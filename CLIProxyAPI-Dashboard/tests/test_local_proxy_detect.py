import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import auth
from backend import local_proxy


class LocalProxyDetectTests(unittest.TestCase):
    def test_remap_only_local_urls(self):
        self.assertEqual(
            local_proxy.remap_local_proxy_url('http://127.0.0.1:7890', 'http://127.0.0.1:7892'),
            'http://127.0.0.1:7892',
        )
        self.assertEqual(
            local_proxy.remap_local_proxy_url('direct', 'http://127.0.0.1:7892'),
            'direct',
        )
        self.assertEqual(
            local_proxy.remap_local_proxy_url('http://proxy.example.com:8080', 'http://127.0.0.1:7892'),
            'http://proxy.example.com:8080',
        )

    def test_rewrite_proxy_url_sets_and_clears(self):
        text = 'host: "127.0.0.1"\nproxy-url: "http://127.0.0.1:7890"\nport: 8318\n'
        rewritten = auth.rewrite_proxy_url(text, 'http://127.0.0.1:7892')
        self.assertIn('proxy-url: "http://127.0.0.1:7892"', rewritten)
        self.assertNotIn('proxy-url: "http://127.0.0.1:7890"', rewritten)
        cleared = auth.rewrite_proxy_url(text, '')
        self.assertNotIn('proxy-url:', cleared)

    def test_detect_prefers_working_port(self):
        with patch.object(local_proxy, 'collect_candidate_ports', return_value=[
            {'port': 7890, 'sources': ['default'], 'weight': 1, 'listening': False},
            {'port': 7892, 'sources': ['maomao-prefs'], 'weight': 16, 'listening': True},
        ]):
            with patch.object(local_proxy, '_port_is_listening', side_effect=lambda port, **kwargs: int(port) == 7892):
                with patch.object(local_proxy, '_probe_http_proxy', side_effect=lambda port, **kwargs: {
                    'port': int(port),
                    'proxy_url': f'http://127.0.0.1:{int(port)}',
                    'listening': int(port) == 7892,
                    'works': int(port) == 7892,
                    'proxy_like': int(port) == 7892,
                    'error': '' if int(port) == 7892 else 'not_listening',
                }):
                    result = local_proxy.detect_local_http_proxy(use_cache=False)
        self.assertTrue(result['ok'])
        self.assertEqual(result['port'], 7892)
        self.assertEqual(result['proxy_url'], 'http://127.0.0.1:7892')

    def test_detect_ignores_dead_prefer_port(self):
        # Stale base-config proxy-url:7890 must not pin CPA after switching to MaoMao 10090.
        with patch.object(local_proxy, 'collect_candidate_ports', return_value=[
            {'port': 10090, 'sources': ['proc:mihomo-windows-386'], 'weight': 32, 'listening': True},
            {'port': 7890, 'sources': ['system-proxy-stale'], 'weight': 1, 'listening': False},
        ]):
            with patch.object(local_proxy, '_port_is_listening', side_effect=lambda port, **kwargs: int(port) == 10090):
                with patch.object(local_proxy, '_probe_http_proxy', side_effect=lambda port, **kwargs: {
                    'port': int(port),
                    'proxy_url': f'http://127.0.0.1:{int(port)}',
                    'listening': int(port) == 10090,
                    'works': int(port) == 10090,
                    'proxy_like': int(port) == 10090,
                    'error': '' if int(port) == 10090 else 'not_listening',
                }):
                    result = local_proxy.detect_local_http_proxy(prefer_port=7890, use_cache=False)
        self.assertTrue(result['ok'])
        self.assertEqual(result['port'], 10090)

    def test_parse_clash_uses_detected_port_when_enabled(self):
        with patch.object(auth, '_detect_active_local_proxy', return_value={
            'ok': True,
            'port': 7892,
            'proxy_url': 'http://127.0.0.1:7892',
            'source': 'maomao-prefs',
        }):
            info = auth._parse_clash_proxy_names(None, detect_active=True)
        self.assertEqual(info['mixed_port'], 7892)
        self.assertEqual(info['detected_proxy_url'], 'http://127.0.0.1:7892')

    def test_parse_clash_skips_detect_by_default(self):
        with patch.object(auth, '_detect_active_local_proxy') as detect:
            info = auth._parse_clash_proxy_names(None)
        detect.assert_not_called()
        self.assertEqual(info['mixed_port'], 0)
        self.assertEqual(info['detected_proxy_url'], '')

    def test_choose_best_egress_includes_direct_and_picks_fastest_ok(self):
        with patch.object(local_proxy, 'list_listening_proxy_ports', return_value=[10090, 7897]):
            with patch.object(local_proxy, 'probe_target_via_proxy') as probe:
                def _side_effect(target_url, proxy_url=None, timeout=4.0, headers=None):
                    proxy = str(proxy_url or 'direct')
                    if proxy.endswith('10090'):
                        return {
                            'ok': False,
                            'proxy_url': proxy,
                            'target_url': target_url,
                            'status': 0,
                            'latency_ms': 80,
                            'error': 'ssl_eof',
                        }
                    if proxy.endswith('7897'):
                        return {
                            'ok': True,
                            'proxy_url': proxy,
                            'target_url': target_url,
                            'status': 200,
                            'latency_ms': 120,
                            'error': '',
                        }
                    return {
                        'ok': True,
                        'proxy_url': 'direct',
                        'target_url': target_url,
                        'status': 200,
                        'latency_ms': 40,
                        'error': '',
                    }

                probe.side_effect = _side_effect
                result = local_proxy.choose_best_egress(
                    'https://apihub.agnes-ai.com/v1',
                    include_direct=True,
                    prefer_proxy_url='http://127.0.0.1:10090',
                )
        self.assertTrue(result['ok'])
        # direct is faster than 7897; dead 10090 is only preferred, not forced
        self.assertEqual(result['proxy_url'], 'direct')

    def test_choose_best_egress_can_prefer_working_local_port(self):
        with patch.object(local_proxy, 'list_listening_proxy_ports', return_value=[7897]):
            with patch.object(local_proxy, 'probe_target_via_proxy') as probe:
                def _side_effect(target_url, proxy_url=None, timeout=4.0, headers=None):
                    proxy = str(proxy_url or 'direct')
                    if proxy == 'direct':
                        return {
                            'ok': False,
                            'proxy_url': 'direct',
                            'target_url': target_url,
                            'status': 0,
                            'latency_ms': 30,
                            'error': 'timeout',
                        }
                    return {
                        'ok': True,
                        'proxy_url': proxy,
                        'target_url': target_url,
                        'status': 200,
                        'latency_ms': 55,
                        'error': '',
                    }

                probe.side_effect = _side_effect
                result = local_proxy.choose_best_egress(
                    'https://apihub.agnes-ai.com/v1',
                    include_direct=True,
                    prefer_proxy_url='http://127.0.0.1:7897',
                )
        self.assertTrue(result['ok'])
        self.assertEqual(result['proxy_url'], 'http://127.0.0.1:7897')


if __name__ == '__main__':
    unittest.main()
