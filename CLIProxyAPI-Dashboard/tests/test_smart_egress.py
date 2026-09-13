import unittest
from unittest.mock import patch, MagicMock

from backend.local_proxy import detect_smart_egress_proxy
from backend.egress_watcher import _watcher_loop, _LAST_STATE, _poll_network_state


class TestSmartEgress(unittest.TestCase):
    def test_smart_egress_tun_active_prioritizes_direct(self):
        tun_info = {'name': 'Mihomo', 'ips': ['198.18.0.1']}
        with patch('backend.local_proxy.get_active_tun_interface', return_value=tun_info):
            result = detect_smart_egress_proxy()
            self.assertTrue(result['ok'])
            self.assertEqual(result['mode'], 'tun')
            self.assertEqual(result['proxy_url'], 'direct')

    def test_smart_egress_system_proxy_when_tun_down(self):
        sys_info = {'port': 7897, 'proxy_url': 'http://127.0.0.1:7897', 'server': '127.0.0.1:7897'}
        with patch('backend.local_proxy.get_active_tun_interface', return_value=None), \
             patch('backend.local_proxy.get_active_system_proxy', return_value=sys_info):
            result = detect_smart_egress_proxy()
            self.assertTrue(result['ok'])
            self.assertEqual(result['mode'], 'system_proxy')
            self.assertEqual(result['proxy_url'], 'http://127.0.0.1:7897')
            self.assertEqual(result['port'], 7897)

    def test_smart_egress_local_port_fallback(self):
        with patch('backend.local_proxy.get_active_tun_interface', return_value=None), \
             patch('backend.local_proxy.get_active_system_proxy', return_value=None), \
             patch('backend.local_proxy.detect_local_http_proxy', return_value={'ok': True, 'port': 7890, 'proxy_url': 'http://127.0.0.1:7890'}):
            result = detect_smart_egress_proxy()
            self.assertTrue(result['ok'])
            self.assertEqual(result['mode'], 'local_port')
            self.assertEqual(result['proxy_url'], 'http://127.0.0.1:7890')

    def test_smart_egress_none_fallback_direct(self):
        with patch('backend.local_proxy.get_active_tun_interface', return_value=None), \
             patch('backend.local_proxy.get_active_system_proxy', return_value=None), \
             patch('backend.local_proxy.detect_local_http_proxy', return_value={'ok': False}):
            result = detect_smart_egress_proxy()
            self.assertFalse(result['ok'])
            self.assertEqual(result['mode'], 'direct')
            self.assertEqual(result['proxy_url'], 'direct')

    def test_watcher_detects_transition_and_rebuilds(self):
        import backend.egress_watcher as ew
        ew._LAST_STATE = {'mode': 'tun', 'proxy_url': 'direct'}

        mock_event = MagicMock()
        # Fire once then exit
        mock_event.wait.side_effect = [False, True]

        with patch('backend.egress_watcher._WATCHER_STOP_EVENT', mock_event), \
             patch('backend.egress_watcher.load_state', return_value={'proxy_auto_detect': True}), \
             patch('backend.egress_watcher._poll_network_state', return_value={'mode': 'system_proxy', 'proxy_url': 'http://127.0.0.1:7897'}), \
             patch('backend.auth.rebuild_runtime_config_from_state') as mock_rebuild:

            ew._watcher_loop(interval_seconds=0.01)
            self.assertEqual(ew._LAST_STATE['mode'], 'system_proxy')
            self.assertEqual(ew._LAST_STATE['proxy_url'], 'http://127.0.0.1:7897')
            mock_rebuild.assert_called_once()

    def test_watcher_ignores_when_auto_detect_disabled(self):
        import backend.egress_watcher as ew
        ew._LAST_STATE = {'mode': 'tun', 'proxy_url': 'direct'}

        mock_event = MagicMock()
        mock_event.wait.side_effect = [False, True]

        with patch('backend.egress_watcher._WATCHER_STOP_EVENT', mock_event), \
             patch('backend.egress_watcher.load_state', return_value={'proxy_auto_detect': False}), \
             patch('backend.auth.rebuild_runtime_config_from_state') as mock_rebuild:

            ew._watcher_loop(interval_seconds=0.01)
            mock_rebuild.assert_not_called()


if __name__ == '__main__':
    unittest.main()
