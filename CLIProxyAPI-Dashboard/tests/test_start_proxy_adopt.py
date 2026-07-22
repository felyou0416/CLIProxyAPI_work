import unittest
from unittest.mock import patch

from backend import processes


class TestStartProxyAdopt(unittest.TestCase):
    def setUp(self):
        processes.processes['proxy'] = None
        processes.processes['access_gateway'] = None

    @patch('backend.processes.start_media_proxy', return_value={'ok': True, 'message': 'media ok'})
    @patch('backend.processes.save_state')
    @patch('backend.processes.stop_pid')
    @patch('backend.processes._managed_listener_info')
    @patch('backend.processes.probe_socket_stack', return_value=None)
    @patch('backend.processes.get_proxy_api_key', return_value='test-key')
    @patch('backend.processes.get_proxy_bind_host', return_value='127.0.0.1')
    @patch('backend.processes.list_auth_files', return_value=[{'id': 'a/1.json', 'name': '1.json', 'provider': 'gemini'}])
    @patch('backend.processes.load_state', return_value={'route_strategy': 'round-robin'})
    @patch('backend.processes.ACCESS_GATEWAY_BINARY')
    @patch('backend.processes._cli_binary_ready', return_value=True)
    def test_adopts_existing_managed_stack(
        self,
        _cli,
        mock_gateway_bin,
        _state,
        _auth,
        _bind,
        _key,
        _socket,
        mock_listener,
        mock_stop,
        mock_save,
        mock_media,
    ):
        mock_gateway_bin.is_file.return_value = True
        mock_listener.side_effect = lambda port: {
            8317: {'pid': 111, 'name': 'cli-access-gateway.exe', 'managed': True},
            8318: {'pid': 222, 'name': 'cli-proxy-api.exe', 'managed': True},
        }.get(port)

        lock = processes.process_lock
        observed = []

        def record_lock_state(*_args, **_kwargs):
            free = lock.acquire(blocking=False)
            if free:
                lock.release()
            observed.append(free)
            return {'ok': True, 'message': 'media ok'}

        mock_media.side_effect = record_lock_state
        result = processes.start_proxy()

        self.assertTrue(result['ok'])
        self.assertTrue(result.get('adopted'))
        self.assertEqual(result.get('core_pid'), 222)
        self.assertEqual(result.get('gateway_pid'), 111)
        self.assertIn('adopted existing instance', result['message'])
        mock_stop.assert_not_called()
        mock_media.assert_called_once()
        mock_save.assert_called_once()
        self.assertTrue(all(observed), 'adopt finalize must not hold process_lock (deadlocks start_media_proxy)')
        # Adopted instances are not attached as in-memory Popen handles.
        self.assertIsNone(processes.processes.get('proxy'))
        self.assertIsNone(processes.processes.get('access_gateway'))

    @patch('backend.processes.subprocess.Popen')
    @patch('backend.processes.wait_for_listener', return_value=True)
    @patch('backend.processes.build_runtime_config')
    @patch('backend.processes.start_media_proxy', return_value={'ok': True, 'message': 'media ok'})
    @patch('backend.processes.save_state')
    @patch('backend.processes.stop_pid', return_value=True)
    @patch('backend.processes._managed_listener_info')
    @patch('backend.processes.probe_socket_stack', return_value=None)
    @patch('backend.processes.get_proxy_api_key', return_value='test-key')
    @patch('backend.processes.get_proxy_bind_host', return_value='127.0.0.1')
    @patch('backend.processes.list_auth_files', return_value=[{'id': 'a/1.json', 'name': '1.json', 'provider': 'gemini'}])
    @patch('backend.processes.load_state', return_value={'route_strategy': 'round-robin'})
    @patch('backend.processes.ACCESS_GATEWAY_BINARY')
    @patch('backend.processes._cli_binary_ready', return_value=True)
    def test_partial_stack_is_reclaimed(
        self,
        _cli,
        mock_gateway_bin,
        _state,
        _auth,
        _bind,
        _key,
        _socket,
        mock_listener,
        mock_stop,
        mock_save,
        mock_media,
        mock_build,
        mock_wait,
        mock_popen,
    ):
        mock_gateway_bin.is_file.return_value = True
        # Only core is leftover; gateway is free → should reclaim and rebuild.
        calls = {'n': 0}

        def listener(port):
            # Initial pair: gateway free, core managed. After stop, both free.
            calls['n'] += 1
            if port == 8318 and calls['n'] <= 2:
                return {'pid': 333, 'name': 'cli-proxy-api.exe', 'managed': True}
            return None

        mock_listener.side_effect = listener

        core_proc = type('P', (), {'pid': 9001, 'poll': lambda self: None})()
        gateway_proc = type('P', (), {'pid': 9002, 'poll': lambda self: None})()
        mock_popen.side_effect = [core_proc, gateway_proc]

        with patch.object(processes, 'CLI_EXE', processes.CLI_EXE):
            result = processes.start_proxy()

        self.assertTrue(result['ok'])
        self.assertFalse(result.get('adopted'))
        mock_stop.assert_called_once_with(333)
        self.assertEqual(mock_popen.call_count, 2)
        mock_build.assert_called_once()

    @patch('backend.processes.stop_pid')
    @patch('backend.processes._managed_listener_info')
    @patch('backend.processes.probe_socket_stack', return_value=None)
    @patch('backend.processes.get_proxy_api_key', return_value='test-key')
    @patch('backend.processes.get_proxy_bind_host', return_value='127.0.0.1')
    @patch('backend.processes.list_auth_files', return_value=[{'id': 'a/1.json', 'name': '1.json'}])
    @patch('backend.processes.load_state', return_value={})
    @patch('backend.processes.ACCESS_GATEWAY_BINARY')
    @patch('backend.processes._cli_binary_ready', return_value=True)
    def test_foreign_occupier_is_rejected(
        self,
        _cli,
        mock_gateway_bin,
        _state,
        _auth,
        _bind,
        _key,
        _socket,
        mock_listener,
        mock_stop,
    ):
        mock_gateway_bin.is_file.return_value = True
        mock_listener.side_effect = lambda port: {
            8317: {'pid': 444, 'name': 'nginx.exe', 'managed': False},
            8318: None,
        }.get(port)

        result = processes.start_proxy()
        self.assertFalse(result['ok'])
        self.assertIn('nginx.exe', result['message'])
        mock_stop.assert_not_called()

    @patch('backend.processes.start_media_proxy', return_value={'ok': True, 'message': 'media ok'})
    @patch('backend.processes.save_state')
    @patch('backend.processes.subprocess.Popen')
    @patch('backend.processes.wait_for_listener')
    @patch('backend.processes.build_runtime_config')
    @patch('backend.processes.stop_pid', return_value=True)
    @patch('backend.processes._managed_listener_info', return_value=None)
    @patch('backend.processes.probe_socket_stack', return_value=None)
    @patch('backend.processes.get_proxy_api_key', return_value='test-key')
    @patch('backend.processes.get_proxy_bind_host', return_value='127.0.0.1')
    @patch('backend.processes.list_auth_files', return_value=[{'id': 'a/1.json', 'name': '1.json', 'provider': 'gemini'}])
    @patch('backend.processes.load_state', return_value={'route_strategy': 'round-robin'})
    @patch('backend.processes.ACCESS_GATEWAY_BINARY')
    @patch('backend.processes._cli_binary_ready', return_value=True)
    def test_wait_for_listener_runs_without_process_lock(
        self,
        _cli,
        mock_gateway_bin,
        _state,
        _auth,
        _bind,
        _key,
        _socket,
        _listener,
        _stop,
        _build,
        mock_wait,
        mock_popen,
        _save,
        _media,
    ):
        mock_gateway_bin.is_file.return_value = True
        core_proc = type('P', (), {'pid': 9001, 'poll': lambda self: None})()
        gateway_proc = type('P', (), {'pid': 9002, 'poll': lambda self: None})()
        mock_popen.side_effect = [core_proc, gateway_proc]
        lock = processes.process_lock
        observed = []

        def record_lock_state(*_args, **_kwargs):
            free = lock.acquire(blocking=False)
            if free:
                lock.release()
            observed.append(free)
            return True

        mock_wait.side_effect = record_lock_state

        result = processes.start_proxy()

        self.assertTrue(result['ok'])
        self.assertGreaterEqual(mock_wait.call_count, 1)
        self.assertTrue(all(observed), 'wait_for_listener must not run while process_lock is held')


if __name__ == '__main__':
    unittest.main()
