import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# We import processes module to test restart_dashboard_panel
from backend import processes

class TestDashboardRestart(unittest.TestCase):
    @patch('backend.processes.time.sleep')
    @patch('backend.processes.os._exit')
    @patch('backend.processes.subprocess.Popen')
    @patch('backend.processes.threading.Thread')
    def test_restart_dashboard_panel_ps1(self, mock_thread, mock_popen, mock_exit, mock_sleep):
        # We want the thread target to execute synchronously during the test
        def mock_thread_init(target, name, daemon):
            # execute the target directly
            target()
            mock = MagicMock()
            return mock

        mock_thread.side_effect = mock_thread_init

        # Mock DASHBOARD_ROOT / 'start_dashboard.ps1' exists
        with patch.object(Path, 'exists', autospec=True) as mock_exists:
            def exists_side_effect(*args, **kwargs):
                return args[0].name == 'start_dashboard.ps1' if args else False
            mock_exists.side_effect = exists_side_effect

            result = processes.restart_dashboard_panel(delay_seconds=0.1)

            # Check return value
            self.assertTrue(result['ok'])
            self.assertEqual(result['message'], 'Dashboard panel is restarting.')

            # Verify sleep was called with correct delay
            mock_sleep.assert_called_once_with(0.1)

            # Verify subprocess.Popen was called with powershell and start_dashboard.ps1
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            cmd_args = args[0]
            self.assertIn('powershell', cmd_args)
            self.assertIn('-File', cmd_args)
            self.assertTrue(any('start_dashboard.ps1' in part for part in cmd_args))

            # Verify os._exit(0) was called
            mock_exit.assert_called_once_with(0)

    @patch('backend.processes.time.sleep')
    @patch('backend.processes.os._exit')
    @patch('backend.processes.subprocess.Popen')
    @patch('backend.processes.threading.Thread')
    def test_restart_dashboard_panel_bat(self, mock_thread, mock_popen, mock_exit, mock_sleep):
        def mock_thread_init(target, name, daemon):
            target()
            mock = MagicMock()
            return mock

        mock_thread.side_effect = mock_thread_init

        # Mock DASHBOARD_ROOT / 'start_dashboard.bat' exists
        with patch.object(Path, 'exists', autospec=True) as mock_exists:
            def exists_side_effect(*args, **kwargs):
                return args[0].name == 'start_dashboard.bat' if args else False
            mock_exists.side_effect = exists_side_effect

            result = processes.restart_dashboard_panel(delay_seconds=0.1)

            self.assertTrue(result['ok'])

            mock_sleep.assert_called_once_with(0.1)

            # Verify subprocess.Popen was called with start_dashboard.bat
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            cmd_args = args[0]
            self.assertTrue(any('start_dashboard.bat' in part for part in cmd_args))

            mock_exit.assert_called_once_with(0)

if __name__ == '__main__':
    unittest.main()
