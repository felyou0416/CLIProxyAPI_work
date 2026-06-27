import unittest

from backend import terminals


class TerminalBufferTests(unittest.TestCase):
    def setUp(self):
        self.old_limit = terminals.MAX_OUTPUT_CHARS
        terminals.MAX_OUTPUT_CHARS = 10
        terminals.terminal_processes.clear()

    def tearDown(self):
        terminals.MAX_OUTPUT_CHARS = self.old_limit
        terminals.terminal_processes.clear()

    def test_read_terminal_uses_monotonic_offsets_after_trim(self):
        terminals.terminal_processes['demo'] = {
            'id': 'demo',
            'kind': 'powershell',
            'title': 'demo',
            'cwd': '.',
            'process': None,
            'created_at': 0,
            'output_chunks': [],
            'output_base_offset': 0,
            'output_size': 0,
            'output': '',
            'trimmed': False,
            'pty': True,
        }

        terminals._append_output('demo', 'abcdef')
        first = terminals.read_terminal('demo', 0)
        self.assertEqual(first['output'], 'abcdef')
        self.assertEqual(first['offset'], 6)

        terminals._append_output('demo', 'ghijkl')
        second = terminals.read_terminal('demo', first['offset'])
        self.assertEqual(second['output'], 'ghijkl')
        self.assertEqual(second['offset'], 12)
        self.assertGreater(second['offset'], first['offset'])

    def test_read_terminal_returns_retained_output_for_stale_offset(self):
        terminals.terminal_processes['demo'] = {
            'id': 'demo',
            'kind': 'powershell',
            'title': 'demo',
            'cwd': '.',
            'process': None,
            'created_at': 0,
            'output_chunks': [],
            'output_base_offset': 0,
            'output_size': 0,
            'output': '',
            'trimmed': False,
            'pty': True,
        }

        terminals._append_output('demo', 'abcdef')
        terminals._append_output('demo', 'ghijkl')
        result = terminals.read_terminal('demo', 0)
        self.assertEqual(result['output'], 'ghijkl')
        self.assertEqual(result['offset'], 12)
        self.assertTrue(result['trimmed'])


if __name__ == '__main__':
    unittest.main()
