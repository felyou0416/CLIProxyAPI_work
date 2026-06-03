import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import security


class SecurityReportTests(unittest.TestCase):
    def test_report_flags_exposure_and_log_leaks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "proxy.stdout.log"
            log_path.write_text('Authorization: Bearer sk-test-secret-value-1234567890', encoding="utf-8")

            auth_items = [
                {"id": "default::manual.json", "manual": True, "provider": "custom"},
            ]
            manual_entries = [
                {
                    "id": "default::manual.json",
                    "provider": "custom",
                    "base_url": "http://insecure.example.com/v1",
                    "models": ["gpt-4.1"],
                    "path": str(Path(tmpdir) / "manual.json"),
                }
            ]

            with patch.object(security, "load_state", return_value={"exposure_enabled": True, "selected_auth_refs": [], "applied_auth_refs": []}), patch.object(
                security,
                "current_status",
                return_value={"proxy_running": True, "bind_host": "0.0.0.0", "exposure_url": "http://10.0.0.2:8317"},
            ), patch.object(security, "get_proxy_api_key", return_value="cliproxyapi"), patch.object(
                security, "list_auth_files", return_value=auth_items
            ), patch.object(
                security, "_collect_manual_auth_metadata", return_value=manual_entries
            ), patch.object(
                security, "list_api_keys", return_value=[]
            ), patch.object(
                security, "STATE_FILE", Path(tmpdir) / "state.json"
            ), patch.object(
                security, "DEVICE_LOGIN_STDOUT", Path(tmpdir) / "device-login.stdout.log"
            ), patch.object(
                security, "DEVICE_LOGIN_STDERR", Path(tmpdir) / "device-login.stderr.log"
            ), patch.object(
                security, "PROXY_STDOUT", log_path
            ), patch.object(
                security, "PROXY_STDERR", Path(tmpdir) / "proxy.stderr.log"
            ), patch.object(
                security, "TOOL_LOGS_DIR", Path(tmpdir) / "tool-logs"
            ):
                report = security.generate_security_report()

        self.assertEqual(report["summary"]["posture"], "critical")
        titles = [item["title"] for item in report["findings"]]
        self.assertIn("Proxy exposure mode is enabled", titles)
        self.assertIn("Exposed proxy is using the default admin API key", titles)
        self.assertIn("Manual provider entries include non-HTTPS upstream URLs", titles)
        self.assertIn("Logs contain values that look like live credentials", titles)


if __name__ == "__main__":
    unittest.main()
