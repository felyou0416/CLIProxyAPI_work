import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, mock_open, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.processes as processes


class MediaProxyProcessTests(unittest.TestCase):
    def test_start_media_proxy_runs_compiled_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            binary = root / 'cli-media-proxy.exe'
            config = root / 'config.example.json'
            binary.write_bytes(b'MZ')
            config.write_text('{}', encoding='utf-8')
            proc = Mock(pid=1234)
            proc.poll.return_value = None

            with patch.object(processes, 'MEDIA_PROXY_ROOT', root), \
                 patch.object(processes, 'MEDIA_PROXY_BINARY', binary), \
                 patch.object(processes, 'MEDIA_PROXY_STDOUT', root / 'stdout.log'), \
                 patch.object(processes, 'MEDIA_PROXY_STDERR', root / 'stderr.log'), \
                 patch.object(processes, 'list_auth_files', return_value=['agnes.json']), \
                 patch.object(processes, 'process_alive', return_value=False), \
                 patch.object(processes, 'find_proxy_listener_pid', return_value=None), \
                 patch.object(processes, 'wait_for_media_proxy_ready', return_value=True), \
                 patch('builtins.open', mock_open()), \
                 patch.object(processes.subprocess, 'Popen', return_value=proc) as popen:
                result = processes.start_media_proxy()

            self.assertTrue(result['ok'])
            command = popen.call_args.args[0]
            self.assertEqual(command[0], str(binary))
            self.assertEqual(command[1:], ['-config', str(config)])
            self.assertNotIn('go', command)


if __name__ == '__main__':
    unittest.main()
