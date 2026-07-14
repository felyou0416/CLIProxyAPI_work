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

    def test_provider_model_delete_rebuilds_runtime_config(self):
        handler = _FakeHandler()
        with patch.object(post_routes, "delete_provider_model_override", return_value={
            "provider": "codex", "upstream_id": "gpt-raw", "call_id": "codex-public",
        }) as delete_mapping, patch.object(
            post_routes, "load_state", return_value={"state": "demo"}
        ) as load_state, patch.object(
            post_routes, "rebuild_runtime_config_from_state", return_value={"rebuilt": True, "validation": {"ok": True}}
        ) as rebuild_runtime:
            handled = post_routes.handle_post(
                handler,
                SimpleNamespace(path="/api/provider-model-delete"),
                {"provider": "codex", "upstream_id": "gpt-raw", "call_id": "codex-public"},
            )

        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        delete_mapping.assert_called_once_with(provider="codex", upstream_id="gpt-raw", call_id="codex-public")
        load_state.assert_called_once()
        rebuild_runtime.assert_called_once_with({"state": "demo"})
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["runtime_rebuilt"])

    def test_aggregate_update_skips_runtime_rebuild(self):
        handler = _FakeHandler()
        with patch.object(post_routes, "create_custom_aggregate_alias", return_value={"alias_id": "demo"}) as create_alias, patch.object(
            post_routes, "current_status", return_value={"proxy_running": True}
        ) as current_status, patch.object(
            post_routes, "load_state", return_value={}
        ) as load_state, patch.object(
            post_routes, "rebuild_runtime_config_from_state", return_value={"rebuilt": True, "validation": {"ok": True}}
        ) as rebuild_runtime, patch.object(
            post_routes, "restart_proxy", return_value={"ok": True, "message": "restarted"}
        ) as restart_proxy:
            handled = post_routes.handle_post(
                handler,
                SimpleNamespace(path="/api/aggregate-models"),
                {"action": "create", "alias_id": "demo"},
            )

        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        create_alias.assert_called_once_with("demo")
        current_status.assert_not_called()
        load_state.assert_not_called()
        rebuild_runtime.assert_not_called()
        restart_proxy.assert_not_called()
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertFalse(payload["runtime_rebuilt"])
        self.assertFalse(payload["proxy_restarted"])
        self.assertFalse(payload["restart_required"])

    def test_aggregate_set_members_does_not_rebuild_when_skip_restart_false(self):
        handler = _FakeHandler()
        with patch.object(post_routes, "set_custom_aggregate_alias_members", return_value={"alias_id": "demo"}) as set_members, patch.object(
            post_routes, "current_status", return_value={"proxy_running": True}
        ) as current_status, patch.object(
            post_routes, "rebuild_runtime_config_from_state", return_value={"rebuilt": True}
        ) as rebuild_runtime, patch.object(
            post_routes, "restart_proxy", return_value={"ok": True}
        ) as restart_proxy:
            handled = post_routes.handle_post(
                handler,
                SimpleNamespace(path="/api/aggregate-models"),
                {"action": "set_members", "alias_id": "demo", "members": [], "skip_restart": False},
            )

        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        set_members.assert_called_once_with("demo", [], None)
        current_status.assert_not_called()
        rebuild_runtime.assert_not_called()
        restart_proxy.assert_not_called()
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertFalse(payload["runtime_rebuilt"])
        self.assertFalse(payload["proxy_restarted"])

    def test_aggregate_apply_runtime_rebuilds_without_restart(self):
        handler = _FakeHandler()
        with patch.object(post_routes, "load_state", return_value={"state": "demo"}) as load_state, patch.object(
            post_routes, "rebuild_runtime_config_from_state", return_value={"rebuilt": True, "validation": {"ok": True}}
        ) as rebuild_runtime, patch.object(
            post_routes, "current_status", return_value={"proxy_running": True}
        ) as current_status, patch.object(
            post_routes, "restart_proxy", return_value={"ok": True}
        ) as restart_proxy:
            handled = post_routes.handle_post(
                handler,
                SimpleNamespace(path="/api/aggregate-models/apply-runtime"),
                {},
            )

        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        load_state.assert_called_once()
        rebuild_runtime.assert_called_once_with({"state": "demo"})
        current_status.assert_called_once()
        restart_proxy.assert_not_called()
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertTrue(payload["runtime_rebuilt"])
        self.assertFalse(payload["proxy_restarted"])
        self.assertTrue(payload["proxy_running"])
        self.assertFalse(payload["restart_required"])

    def test_aggregate_apply_runtime_reports_no_rebuild(self):
        handler = _FakeHandler()
        with patch.object(post_routes, "load_state", return_value={}) as load_state, patch.object(
            post_routes, "rebuild_runtime_config_from_state", return_value={"rebuilt": False, "validation": {"ok": True}}
        ) as rebuild_runtime, patch.object(
            post_routes, "current_status", return_value={"proxy_running": False}
        ), patch.object(
            post_routes, "restart_proxy", return_value={"ok": True}
        ) as restart_proxy:
            handled = post_routes.handle_post(
                handler,
                SimpleNamespace(path="/api/aggregate-models/apply-runtime"),
                {},
            )

        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        load_state.assert_called_once()
        rebuild_runtime.assert_called_once_with({})
        restart_proxy.assert_not_called()
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertFalse(payload["runtime_rebuilt"])
        self.assertFalse(payload["restart_required"])

    def test_aggregate_apply_runtime_reports_validation_failure(self):
        handler = _FakeHandler()
        with patch.object(post_routes, "load_state", return_value={}), patch.object(
            post_routes,
            "rebuild_runtime_config_from_state",
            return_value={
                "rebuilt": False,
                "reason": "validation_failed",
                "error": "bad config",
                "validation": {"ok": False, "message": "bad config"},
            },
        ), patch.object(
            post_routes, "current_status", return_value={"proxy_running": True}
        ) as current_status, patch.object(
            post_routes, "restart_proxy", return_value={"ok": True}
        ) as restart_proxy:
            handled = post_routes.handle_post(
                handler,
                SimpleNamespace(path="/api/aggregate-models/apply-runtime"),
                {},
            )

        self.assertTrue(handled)
        self.assertEqual(handler.status, 500)
        current_status.assert_not_called()
        restart_proxy.assert_not_called()
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["runtime_rebuilt"])

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
