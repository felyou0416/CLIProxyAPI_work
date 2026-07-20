import base64
import json
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend import processes


class TestDashboardRestart(unittest.TestCase):
    def setUp(self):
        processes._DASHBOARD_EXIT_SCHEDULED = False
        processes._DASHBOARD_RESTART_SCHEDULED = False
        stamp = processes._dashboard_restart_stamp_path()
        if stamp.exists():
            stamp.unlink()

    def tearDown(self):
        processes._DASHBOARD_EXIT_SCHEDULED = False
        processes._DASHBOARD_RESTART_SCHEDULED = False
        stamp = processes._dashboard_restart_stamp_path()
        if stamp.exists():
            stamp.unlink()

    @patch('backend.processes.time.sleep')
    @patch('backend.processes.os._exit')
    @patch('backend.processes.subprocess.Popen')
    @patch('backend.processes.threading.Thread')
    @patch('backend.processes.os.getpid', return_value=4242)
    @patch('backend.processes.get_dashboard_port', return_value=8765)
    def test_restart_dashboard_panel_ps1(self, _port, _pid, mock_thread, mock_popen, mock_exit, mock_sleep):
        def mock_thread_init(target, name=None, daemon=None):
            target()
            return MagicMock()

        mock_thread.side_effect = mock_thread_init
        mock_popen.return_value = MagicMock()

        ps_path = processes.DASHBOARD_ROOT / 'start_dashboard.ps1'

        def exists_side_effect(self):
            return self == ps_path

        with patch.object(Path, 'exists', exists_side_effect):
            result = processes.restart_dashboard_panel(delay_seconds=0.1)

        self.assertTrue(result['ok'])
        self.assertEqual(result['message'], 'Dashboard panel is restarting.')
        self.assertEqual(result['pid'], 4242)
        self.assertEqual(result['port'], 8765)
        self.assertTrue(result.get('token'))

        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        cmd_args = args[0]
        self.assertIn('powershell', cmd_args)
        self.assertIn('-EncodedCommand', cmd_args)
        encoded = cmd_args[cmd_args.index('-EncodedCommand') + 1]
        decoded = base64.b64decode(encoded).decode('utf-16le')
        # Must wait for PID and abort (not force-start) on timeout.
        self.assertIn('4242', decoded)
        self.assertIn('aborting relaunch', decoded)
        self.assertNotIn('forcing start anyway', decoded)
        self.assertTrue(kwargs.get('close_fds'))

        mock_sleep.assert_called_once_with(0.4)  # settle floor
        mock_exit.assert_called_once_with(0)

        stamp = processes._read_dashboard_restart_stamp()
        self.assertIsNotNone(stamp)
        self.assertEqual(stamp.get('token'), result.get('token'))

    @patch('backend.processes.time.sleep')
    @patch('backend.processes.os._exit')
    @patch('backend.processes.subprocess.Popen')
    @patch('backend.processes.threading.Thread')
    @patch('backend.processes.os.getpid', return_value=5151)
    @patch('backend.processes.get_dashboard_port', return_value=8765)
    def test_restart_dashboard_panel_bat(self, _port, _pid, mock_thread, mock_popen, mock_exit, mock_sleep):
        def mock_thread_init(target, name=None, daemon=None):
            target()
            return MagicMock()

        mock_thread.side_effect = mock_thread_init
        mock_popen.return_value = MagicMock()

        bat_path = processes.DASHBOARD_ROOT / 'start_dashboard.bat'

        def exists_side_effect(self):
            return self == bat_path

        with patch.object(Path, 'exists', exists_side_effect):
            result = processes.restart_dashboard_panel(delay_seconds=0.1)

        self.assertTrue(result['ok'])
        mock_popen.assert_called_once()
        args, _kwargs = mock_popen.call_args
        cmd_args = args[0]
        encoded = cmd_args[cmd_args.index('-EncodedCommand') + 1]
        decoded = base64.b64decode(encoded).decode('utf-16le')
        self.assertIn('start_dashboard.bat', decoded)
        self.assertIn('5151', decoded)
        mock_exit.assert_called_once_with(0)

    @patch('backend.processes.subprocess.Popen')
    @patch('backend.processes.threading.Thread')
    def test_restart_dashboard_panel_missing_script(self, mock_thread, mock_popen):
        with patch.object(Path, 'exists', return_value=False):
            result = processes.restart_dashboard_panel(delay_seconds=0.1)

        self.assertFalse(result['ok'])
        self.assertIn('start script was not found', result['message'])
        mock_popen.assert_not_called()
        mock_thread.assert_not_called()

    @patch('backend.processes.time.sleep')
    @patch('backend.processes.os._exit')
    @patch('backend.processes.subprocess.Popen')
    @patch('backend.processes.threading.Thread')
    @patch('backend.processes.os.getpid', return_value=9001)
    @patch('backend.processes.get_dashboard_port', return_value=8765)
    def test_restart_single_flight_in_process(self, _port, _pid, mock_thread, mock_popen, mock_exit, mock_sleep):
        def mock_thread_init(target, name=None, daemon=None):
            # Do not execute exit immediately — leave scheduled flags set.
            return MagicMock()

        mock_thread.side_effect = mock_thread_init
        mock_popen.return_value = MagicMock()
        ps_path = processes.DASHBOARD_ROOT / 'start_dashboard.ps1'

        def exists_side_effect(self):
            return self == ps_path

        with patch.object(Path, 'exists', exists_side_effect):
            first = processes.restart_dashboard_panel(delay_seconds=0.2)
            second = processes.restart_dashboard_panel(delay_seconds=0.2)

        self.assertTrue(first['ok'])
        self.assertFalse(second['ok'])
        self.assertIn('already scheduled', second['message'])
        self.assertEqual(mock_popen.call_count, 1)
        mock_exit.assert_not_called()

    @patch('backend.processes.subprocess.Popen')
    @patch('backend.processes.threading.Thread')
    def test_restart_cooldown_blocks_repeat(self, mock_thread, mock_popen):
        processes._write_dashboard_restart_stamp({
            'token': 'old-token',
            'pid': 1,
            'port': 8765,
            'scheduled_at': time.time(),
        })
        result = processes.restart_dashboard_panel(delay_seconds=0.1)
        self.assertFalse(result['ok'])
        self.assertIn('already in progress', result['message'])
        mock_popen.assert_not_called()
        mock_thread.assert_not_called()

    def test_stale_cooldown_stamp_is_ignored(self):
        processes._write_dashboard_restart_stamp({
            'token': 'stale',
            'pid': 1,
            'port': 8765,
            'scheduled_at': time.time() - 120,
        })
        blocked = processes._dashboard_restart_in_cooldown()
        self.assertIsNone(blocked)


if __name__ == '__main__':
    unittest.main()
