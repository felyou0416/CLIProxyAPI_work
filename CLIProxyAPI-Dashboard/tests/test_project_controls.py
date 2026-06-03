import unittest
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

from backend import processes
from backend.routes import post_routes


class _FakeHandler:
    def __init__(self):
        self.status = None
        self.headers = {}
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        return None


class ProjectControlTests(unittest.TestCase):
    def test_start_project_short_circuits_when_proxy_is_running(self):
        with patch.object(processes, "current_status", return_value={"proxy_running": True}):
            result = processes.start_project()
        self.assertTrue(result["ok"])
        self.assertTrue(result["project_running"])
        self.assertEqual(result["message"], "Project is already running.")

    def test_start_project_delegates_to_start_proxy(self):
        with patch.object(processes, "current_status", return_value={"proxy_running": False}), patch.object(
            processes, "start_proxy", return_value={"ok": True, "message": "Started RelayX with auth pool: demo"}
        ):
            result = processes.start_project()
        self.assertTrue(result["ok"])
        self.assertTrue(result["project_running"])
        self.assertTrue(result["proxy_running"])

    def test_start_project_route_delegates_to_project_start(self):
        handler = _FakeHandler()
        with patch.object(
            post_routes, "start_project", return_value={"ok": True, "message": "Started RelayX.", "proxy_running": True}
        ) as start_project:
            handled = post_routes.handle_post(handler, SimpleNamespace(path="/api/start-project"), {})
        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        start_project.assert_called_once()
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertTrue(payload["proxy_running"])

    def test_stop_project_stops_proxy_and_device_login_then_shutdown_all(self):
        with patch.object(processes, "stop_proxy", return_value={"ok": True, "message": "Stopped RelayX."}) as stop_proxy, patch.object(
            processes, "stop_device_login", return_value={"ok": True, "message": "Stopped device login."}
        ) as stop_login, patch.object(processes, "shutdown_all") as shutdown_all:
            result = processes.stop_project()
        self.assertTrue(result["ok"])
        self.assertFalse(result["project_running"])
        stop_proxy.assert_called_once()
        stop_login.assert_called_once()
        shutdown_all.assert_called_once()


if __name__ == "__main__":
    unittest.main()
