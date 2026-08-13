"""Local-only dashboard links and explicitly configured service actions."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from backend.paths import DASHBOARD_ROOT


LOCAL_WORKSPACE_DIR = Path(
    os.environ.get("CLIPROXYAPI_DASHBOARD_LOCAL_DIR", "")
).expanduser() if os.environ.get("CLIPROXYAPI_DASHBOARD_LOCAL_DIR", "").strip() else DASHBOARD_ROOT / ".local"
LOCAL_WORKSPACE_FILE = LOCAL_WORKSPACE_DIR / "dashboard-actions.json"

_ALLOWED_OPERATIONS = ("start", "restart", "stop")
_BUILTIN_SERVICE_OPERATIONS = {
    "openclaw": ("start", "restart", "stop"),
    "oauth": ("start", "restart", "stop"),
    "create-grok": ("start", "restart", "stop"),
    "77chat": ("start", "restart", "stop"),
    "tunnel": ("start", "restart", "stop"),
    "grok2api": ("start", "restart", "stop"),
    "grok2api-frontend": ("start", "restart", "stop"),
    "grok2api-backend": ("start", "restart", "stop"),
}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_ITEMS = 64
_MAX_ARGUMENTS = 32
_MAX_ARGUMENT_LENGTH = 2048


def _text(value, *, field: str, maximum: int, required: bool = False) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{field} is required.")
    if len(result) > maximum:
        raise ValueError(f"{field} is too long.")
    return result


def _id(value, *, field: str) -> str:
    result = _text(value, field=field, maximum=64, required=True)
    if not _ID_RE.fullmatch(result):
        raise ValueError(f"{field} contains unsupported characters.")
    return result


def _command(value, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty argument list.")
    if len(value) > _MAX_ARGUMENTS:
        raise ValueError(f"{field} has too many arguments.")
    result = []
    for index, item in enumerate(value):
        result.append(_text(item, field=f"{field}[{index}]", maximum=_MAX_ARGUMENT_LENGTH, required=True))
    return result


def _url(value, *, field: str) -> str:
    result = _text(value, field=field, maximum=2048, required=True)
    parsed = urlsplit(result)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an http(s) URL.")
    return result


def _normalize_link(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"links[{index}] must be an object.")
    return {
        "id": _id(raw.get("id"), field=f"links[{index}].id"),
        "label": _text(raw.get("label"), field=f"links[{index}].label", maximum=120, required=True),
        "description": _text(raw.get("description"), field=f"links[{index}].description", maximum=300),
        "icon": _text(raw.get("icon"), field=f"links[{index}].icon", maximum=16),
        "url": _url(raw.get("url"), field=f"links[{index}].url"),
    }


def _normalize_service(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"services[{index}] must be an object.")
    prefix = f"services[{index}]"
    service_id = _id(raw.get("id"), field=f"{prefix}.id")
    builtin = _text(raw.get("builtin"), field=f"{prefix}.builtin", maximum=64)
    if builtin and builtin not in _BUILTIN_SERVICE_OPERATIONS:
        raise ValueError(f"{prefix}.builtin is not supported.")

    commands = raw.get("commands", {})
    if not isinstance(commands, dict):
        raise ValueError(f"{prefix}.commands must be an object.")
    normalized_commands = {}
    for operation in _ALLOWED_OPERATIONS:
        if operation in commands:
            normalized_commands[operation] = _command(commands[operation], field=f"{prefix}.commands.{operation}")
    if not builtin and not normalized_commands:
        raise ValueError(f"{prefix}.commands must configure at least one operation.")

    actions = list(_BUILTIN_SERVICE_OPERATIONS[builtin]) if builtin else list(normalized_commands)
    cwd = _text(raw.get("cwd"), field=f"{prefix}.cwd", maximum=2048)
    return {
        "id": service_id,
        "label": _text(raw.get("label"), field=f"{prefix}.label", maximum=120, required=True),
        "description": _text(raw.get("description"), field=f"{prefix}.description", maximum=300),
        "icon": _text(raw.get("icon"), field=f"{prefix}.icon", maximum=16),
        "url": _url(raw.get("url"), field=f"{prefix}.url") if raw.get("url") else "",
        "builtin": builtin,
        "cwd": cwd,
        "commands": normalized_commands,
        "actions": actions,
    }


def _normalize_config(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("The local workspace config must be an object.")
    links = raw.get("links", [])
    services = raw.get("services", [])
    if not isinstance(links, list) or not isinstance(services, list):
        raise ValueError("links and services must be arrays.")
    if len(links) > _MAX_ITEMS or len(services) > _MAX_ITEMS:
        raise ValueError(f"A maximum of {_MAX_ITEMS} links and services is supported.")

    normalized = {
        "title": _text(raw.get("title"), field="title", maximum=120) or "本地工作台",
        "description": _text(raw.get("description"), field="description", maximum=300),
        "links": [_normalize_link(item, index) for index, item in enumerate(links)],
        "services": [_normalize_service(item, index) for index, item in enumerate(services)],
    }
    ids = [item["id"] for item in normalized["links"] + normalized["services"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Link and service ids must be unique.")
    return normalized


def load_local_workspace() -> tuple[dict, str | None]:
    """Return normalized local config and a validation error, if any."""
    if not LOCAL_WORKSPACE_FILE.is_file():
        return {"title": "本地工作台", "description": "", "links": [], "services": []}, None
    try:
        raw = json.loads(LOCAL_WORKSPACE_FILE.read_text(encoding="utf-8"))
        return _normalize_config(raw), None
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"title": "本地工作台", "description": "", "links": [], "services": []}, str(exc)


def public_local_workspace() -> dict:
    """Return only data needed for rendering; never expose commands or cwd."""
    config, error = load_local_workspace()
    services = []
    for service in config["services"]:
        services.append({
            key: service[key]
            for key in ("id", "label", "description", "icon", "url", "builtin")
        } | {"actions": service["actions"]})
    return {
        "title": config["title"],
        "description": config["description"],
        "links": config["links"],
        "services": services,
        "configured": bool(config["links"] or services),
        "config_error": error,
    }


def _run_builtin_service_action(builtin: str, operation: str) -> dict:
    from backend import processes

    handlers = {
        "openclaw": {
            "start": processes.start_openclaw_gateway,
            "restart": processes.restart_openclaw_gateway,
            "stop": processes.stop_openclaw_gateway,
        },
        "oauth": {
            "start": processes.start_oauth_manager,
            "restart": processes.restart_oauth_manager,
            "stop": processes.stop_oauth_manager,
        },
        "create-grok": {
            "start": processes.start_create_grok,
            "restart": processes.restart_create_grok,
            "stop": processes.stop_create_grok,
        },
        "77chat": {
            "start": processes.start_chat77,
            "restart": processes.restart_chat77,
            "stop": processes.stop_chat77,
        },
        "tunnel": {
            "start": processes.start_cloudflared_tunnel,
            "restart": processes.restart_cloudflared_tunnel,
            "stop": processes.stop_cloudflared_tunnel,
        },
        "grok2api": {
            "start": processes.start_grok2api,
            "restart": processes.restart_grok2api,
            "stop": processes.stop_grok2api,
        },
        "grok2api-frontend": {
            "start": processes.start_grok2api_frontend,
            "restart": processes.restart_grok2api_frontend,
            "stop": processes.stop_grok2api_frontend,
        },
        "grok2api-backend": {
            "start": processes.start_grok2api_backend,
            "restart": processes.restart_grok2api_backend,
            "stop": processes.stop_grok2api_backend,
        },
    }
    return handlers[builtin][operation]()


def run_local_service_action(service_id: str, operation: str) -> dict:
    service_id = _id(service_id, field="service_id")
    operation = _text(operation, field="operation", maximum=16, required=True).lower()
    if operation not in _ALLOWED_OPERATIONS:
        raise ValueError(f"Unsupported operation: {operation}")

    config, error = load_local_workspace()
    if error:
        raise ValueError(f"Invalid local workspace config: {error}")
    service = next((item for item in config["services"] if item["id"] == service_id), None)
    if service is None:
        raise ValueError(f"Unknown local service: {service_id}")
    if operation not in service["actions"]:
        raise ValueError(f"Operation '{operation}' is not configured for service '{service_id}'.")
    if service["builtin"]:
        return _run_builtin_service_action(service["builtin"], operation)

    command = service["commands"][operation]
    cwd = service["cwd"] or str(LOCAL_WORKSPACE_DIR)
    cwd_path = Path(cwd).expanduser()
    if not cwd_path.is_absolute():
        cwd_path = LOCAL_WORKSPACE_DIR / cwd_path
    if not cwd_path.is_dir():
        raise ValueError(f"Working directory does not exist: {cwd_path}")

    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd_path),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise ValueError(f"Could not launch local service: {exc}") from exc
    return {
        "ok": True,
        "message": f"{service['label']} {operation} command started.",
        "service_id": service_id,
        "operation": operation,
        "pid": process.pid,
    }
