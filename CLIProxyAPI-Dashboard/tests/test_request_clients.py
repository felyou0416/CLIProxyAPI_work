import json
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.request_metrics.parsing import _parse_request_log_file
from backend.request_metrics.summary import summarize_clients


class RequestClientIPTests(unittest.TestCase):
    def test_parse_request_log_prefers_forwarded_for(self):
        content = '''=== REQUEST INFO ===
URL: /v1/messages?beta=true
Method: POST
Timestamp: 2026-06-08T12:00:00Z

=== HEADERS ===
Host: localhost
X-Forwarded-For: 203.0.113.10, 127.0.0.1
X-Real-IP: 198.51.100.5

=== REQUEST BODY ===
{"model":"opencode/test"}

=== RESPONSE ===
Status: 200
'''
        stat = type('Stat', (), {'st_mtime': 0})()
        item = _parse_request_log_file(pathlib.Path('v1-messages-testid.log'), content, stat)
        self.assertIsNotNone(item)
        self.assertEqual(item['client_ip'], '203.0.113.10')
        self.assertEqual(item['client_ip_source'], 'x-forwarded-for')

    def test_summarize_clients_adds_status_and_error_rate(self):
        # Isolate from live virtual keys / default key so only the two events form one group.
        with patch('backend.request_metrics.summary._build_api_key_label_map', return_value={}), \
             patch('backend.request_metrics.summary._get_default_api_key_masked', return_value='clip...yapi'):
            rows = summarize_clients([
                {'client_ip': '127.0.0.1', 'success': True, 'status_code': 200, 'timestamp': 10, 'latency_ms': 12, 'path': '/v1/models', 'requested_model': '', 'total_tokens': 0},
                {'client_ip': '127.0.0.1', 'success': False, 'status_code': 500, 'timestamp': 11, 'latency_ms': 24, 'path': '/v1/messages', 'requested_model': 'test', 'total_tokens': 5},
            ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ip_type'], 'loopback')
        self.assertEqual(rows[0]['failure_count'], 1)
        self.assertEqual(rows[0]['error_rate'], 0.5)
        self.assertEqual(rows[0]['status'], 'warning')


if __name__ == '__main__':
    unittest.main()
