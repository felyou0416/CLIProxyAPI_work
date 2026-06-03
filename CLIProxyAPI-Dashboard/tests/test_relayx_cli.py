import io
import json
import unittest
from unittest.mock import patch

import relayx_cli


class RelayXCliTests(unittest.TestCase):
    def test_auth_list_filters_provider(self):
        args = relayx_cli._parse_args(["auth", "list", "--provider", "codex"])
        with patch.object(
            relayx_cli,
            "list_auth_files",
            return_value=[
                {"id": "a", "provider": "codex"},
                {"id": "b", "provider": "openrouter"},
            ],
        ):
            result = relayx_cli.dispatch(args)
        self.assertTrue(result["ok"])
        self.assertEqual([item["id"] for item in result["items"]], ["a"])

    def test_auth_select_updates_state(self):
        args = relayx_cli._parse_args(["auth", "select", "--id", "default::one.json", "--id", "default::two.json"])
        fake_items = [
            {"id": "default::one.json", "name": "one.json"},
            {"id": "default::two.json", "name": "two.json"},
        ]
        saved = {}
        with patch.object(relayx_cli, "list_auth_files", return_value=fake_items), patch.object(
            relayx_cli, "load_state", return_value={}
        ), patch.object(relayx_cli, "save_state", side_effect=lambda payload: saved.update(payload)):
            result = relayx_cli.dispatch(args)
        self.assertTrue(result["ok"])
        self.assertEqual(saved["selected_auth"], "one.json")
        self.assertEqual(saved["selected_auth_refs"], ["default::one.json", "default::two.json"])

    def test_tools_list_formats_output(self):
        args = relayx_cli._parse_args(["tools", "list"])
        fake_outputs = {
            "running": {"help": True},
            "states": {"help": {"pid": 123, "returncode": None, "error": None}},
        }
        with patch.dict(relayx_cli.TOOL_DEFS, {"help": {"desc": "Show help"}}, clear=True), patch.object(
            relayx_cli, "get_tool_outputs", return_value=fake_outputs
        ):
            result = relayx_cli.dispatch(args)
        self.assertTrue(result["ok"])
        self.assertEqual(result["items"][0]["id"], "help")
        self.assertTrue(result["items"][0]["running"])

    def test_status_redacts_logs_and_api_key_by_default(self):
        args = relayx_cli._parse_args(["status"])
        with patch.object(
            relayx_cli,
            "current_status",
            return_value={
                "api_key": "cliproxyapi-secret",
                "proxy_stdout": "secret log",
                "proxy_running": True,
            },
        ):
            result = relayx_cli.dispatch(args)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"]["api_key"], "clip***et")
        self.assertNotIn("proxy_stdout", result["status"])

    def test_state_redacts_sensitive_values_by_default(self):
        args = relayx_cli._parse_args(["state"])
        with patch.object(
            relayx_cli,
            "load_state",
            return_value={"exposure_api_key": "cliproxyapi-secret", "notes": "ok"},
        ):
            result = relayx_cli.dispatch(args)
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["exposure_api_key"], "clip***et")
        self.assertEqual(result["state"]["notes"], "ok")

    def test_audit_security_returns_report(self):
        args = relayx_cli._parse_args(["audit", "security"])
        fake_report = {"summary": {"critical": 1, "high": 0, "medium": 0, "low": 0, "info": 0}}
        with patch.object(relayx_cli, "generate_security_report", return_value=fake_report):
            result = relayx_cli.dispatch(args)
        self.assertTrue(result["ok"])
        self.assertEqual(result["report"], fake_report)

    def test_main_prints_json_error_and_returns_nonzero(self):
        stdout = io.StringIO()
        with patch.object(relayx_cli, "dispatch", side_effect=RuntimeError("boom")), patch(
            "sys.stdout", stdout
        ):
            code = relayx_cli.main(["status"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "boom")
