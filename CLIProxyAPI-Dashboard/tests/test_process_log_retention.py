import ast
import inspect
import unittest

from backend import processes


class ProcessLogRetentionTests(unittest.TestCase):
    def test_start_proxy_appends_proxy_stdout_and_stderr(self):
        tree = ast.parse(inspect.getsource(processes.start_proxy))
        opened_modes = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != 'open':
                continue
            if len(node.args) < 2:
                continue
            target = node.args[0]
            mode = node.args[1]
            if isinstance(target, ast.Name) and target.id in {'PROXY_STDOUT', 'PROXY_STDERR'} and isinstance(mode, ast.Constant):
                opened_modes.append((target.id, mode.value))
        self.assertIn(('PROXY_STDOUT', 'a'), opened_modes)
        self.assertIn(('PROXY_STDERR', 'a'), opened_modes)
        self.assertNotIn(('PROXY_STDOUT', 'w'), opened_modes)
        self.assertNotIn(('PROXY_STDERR', 'w'), opened_modes)


if __name__ == '__main__':
    unittest.main()
