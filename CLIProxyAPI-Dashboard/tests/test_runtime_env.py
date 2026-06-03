import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import runtime_env


class RuntimeEnvTests(unittest.TestCase):
    def test_dashboard_auto_start_defaults_to_windows_only(self):
        with patch.object(runtime_env, "is_windows", return_value=True), patch.dict(os.environ, {}, clear=False):
            self.assertTrue(runtime_env.dashboard_auto_start_enabled())
        with patch.object(runtime_env, "is_windows", return_value=False), patch.dict(os.environ, {}, clear=False):
            self.assertFalse(runtime_env.dashboard_auto_start_enabled())

    def test_resolve_cli_binary_prefers_proxy_project_bin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            proxy_root = root / "CLIProxyAPI"
            bin_dir = proxy_root / "CLIProxyAPI" / "bin"
            bin_dir.mkdir(parents=True)
            binary = bin_dir / "cli-proxy-api.exe"
            binary.write_text("", encoding="utf-8")
            with patch.object(runtime_env, "is_windows", return_value=True), patch.dict(os.environ, {}, clear=False):
                resolved = runtime_env.resolve_cli_binary(proxy_root)
            self.assertEqual(resolved, binary)

    def test_resolve_cli_binary_linux_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proxy_root = Path(tmpdir)
            bin_dir = proxy_root / "CLIProxyAPI" / "bin"
            bin_dir.mkdir(parents=True)
            binary = bin_dir / "cli-proxy-api"
            binary.write_text("", encoding="utf-8")
            with patch.object(runtime_env, "is_windows", return_value=False), patch.dict(os.environ, {}, clear=False):
                resolved = runtime_env.resolve_cli_binary(proxy_root)
            self.assertEqual(resolved, binary)


if __name__ == "__main__":
    unittest.main()
