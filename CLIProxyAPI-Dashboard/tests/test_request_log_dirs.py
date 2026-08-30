import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.paths import ACTIVE_AUTH_DIR, AUTH_DIR, LEGACY_REQUEST_LOG_DIR, REQUEST_LOG_DIR
from backend.request_metrics.parsing import _request_log_dirs


class RequestLogDirsTests(unittest.TestCase):
    def test_includes_active_runtime_auth_logs_first(self):
        dirs = _request_log_dirs()
        self.assertTrue(dirs, 'request log dirs should not be empty')
        self.assertEqual(dirs[0], ACTIVE_AUTH_DIR / 'logs')
        self.assertIn(REQUEST_LOG_DIR, dirs)
        self.assertIn(AUTH_DIR / 'logs', dirs)
        self.assertIn(LEGACY_REQUEST_LOG_DIR, dirs)
        # Active runtime logs must win over archived locations.
        self.assertLess(dirs.index(ACTIVE_AUTH_DIR / 'logs'), dirs.index(AUTH_DIR / 'logs'))


if __name__ == '__main__':
    unittest.main()
