import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.auth import (  # noqa: E402
    create_manual_auth_entry,
    delete_auth_entries,
    get_configured_aggregate_models,
    get_configured_provider_models,
    list_auth_files,
    rebuild_runtime_config_from_state,
)
from backend.processes import current_status, restart_proxy, start_proxy, stop_proxy  # noqa: E402
from backend.security import generate_security_report  # noqa: E402
from backend.state import load_state, save_state  # noqa: E402
from backend.tools import (  # noqa: E402
    TOOL_DEFS,
    get_provider_model_test_state,
    get_tool_outputs,
    query_models,
    run_tool,
    stop_tool,
    test_proxy,
)


def _print_json(payload, *, compact=False):
    if compact:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def _mask_value(value, *, prefix=4, suffix=2):
    text = str(value or "").strip()
    if not text:
        return text
    if len(text) <= prefix + suffix:
        return "*" * len(text)
    return f"{text[:prefix]}***{text[-suffix:]}"


def _redact_mapping(payload):
    if isinstance(payload, dict):
        redacted = {}
        for key, value in payload.items():
            key_text = str(key or "").strip().lower()
            if key_text in {"api_key", "exposure_api_key", "last_proxy_api_key"}:
                redacted[key] = _mask_value(value)
            else:
                redacted[key] = _redact_mapping(value)
        return redacted
    if isinstance(payload, list):
        return [_redact_mapping(item) for item in payload]
    return payload


def _redact_status(payload, *, include_logs=False):
    status = dict(payload or {})
    if "api_key" in status:
        status["api_key"] = _mask_value(status.get("api_key"))
    if not include_logs:
        for key in ("device_login_stdout", "device_login_stderr", "proxy_stdout", "proxy_stderr"):
            status.pop(key, None)
    return status


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="RelayX agent-facing CLI for auth inventory, runtime state, and local proxy operations."
    )
    parser.add_argument("--compact", action="store_true", help="Emit compact one-line JSON.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show current RelayX runtime status.")
    status_parser.add_argument("--include-logs", action="store_true", help="Include runtime log tails.")

    state_parser = subparsers.add_parser("state", help="Show persisted dashboard state.")
    state_parser.add_argument("--include-secrets", action="store_true", help="Show raw sensitive values.")

    auth_parser = subparsers.add_parser("auth", help="Manage auth inventory and selection.")
    auth_sub = auth_parser.add_subparsers(dest="auth_command", required=True)

    auth_list = auth_sub.add_parser("list", help="List auth files.")
    auth_list.add_argument("--provider", help="Filter by provider.")
    auth_list.add_argument("--source", help="Filter by sourceId.")
    auth_list.add_argument("--manual-only", action="store_true", help="Only show manual API-key entries.")

    auth_select = auth_sub.add_parser("select", help="Select one or more auth refs for the active pool.")
    auth_select.add_argument("--id", dest="ids", action="append", required=True, help="Auth ref to select. Repeatable.")

    auth_sub.add_parser("clear", help="Clear the selected auth pool.")

    auth_delete = auth_sub.add_parser("delete", help="Delete auth refs from storage.")
    auth_delete.add_argument("--id", dest="ids", action="append", required=True, help="Auth ref to delete. Repeatable.")

    auth_create = auth_sub.add_parser("create-manual", help="Create a manual API-key auth entry.")
    auth_create.add_argument("--base-url", required=True)
    auth_create.add_argument("--model", required=True)
    auth_create.add_argument("--api-key", required=True)
    auth_create.add_argument("--provider")
    auth_create.add_argument("--remark")

    proxy_parser = subparsers.add_parser("proxy", help="Operate the local RelayX proxy runtime.")
    proxy_sub = proxy_parser.add_subparsers(dest="proxy_command", required=True)
    proxy_sub.add_parser("start")
    proxy_sub.add_parser("stop")
    proxy_sub.add_parser("restart")
    proxy_sub.add_parser("query-models", help="Call local /v1/models through RelayX.")
    proxy_sub.add_parser("test", help="Send a simple test request through RelayX.")

    runtime_parser = subparsers.add_parser("runtime", help="Runtime config maintenance helpers.")
    runtime_sub = runtime_parser.add_subparsers(dest="runtime_command", required=True)
    runtime_sub.add_parser("rebuild", help="Rebuild runtime config from persisted state.")

    audit_parser = subparsers.add_parser("audit", help="Run read-only RelayX audits.")
    audit_sub = audit_parser.add_subparsers(dest="audit_command", required=True)
    audit_security = audit_sub.add_parser("security", help="Inspect auth, provider, runtime, and log risks.")
    audit_security.add_argument("--include-paths", action="store_true", help="Include full local file paths in evidence.")

    models_parser = subparsers.add_parser("models", help="Inspect provider and aggregate model maps.")
    models_sub = models_parser.add_subparsers(dest="models_command", required=True)
    provider_parser = models_sub.add_parser("provider", help="Show provider model mappings.")
    provider_parser.add_argument("--runtime", action="store_true", help="Mark runtime test state in the result.")
    models_sub.add_parser("aggregate", help="Show aggregate model aliases.")
    models_sub.add_parser("provider-test-state", help="Show cached provider model test state.")

    tools_parser = subparsers.add_parser("tools", help="Manage bundled RelayX external tools.")
    tools_sub = tools_parser.add_subparsers(dest="tools_command", required=True)
    tools_sub.add_parser("list", help="List available tools and running state.")
    tools_run = tools_sub.add_parser("run", help="Start a bundled tool.")
    tools_run.add_argument("--tool", required=True, choices=sorted(TOOL_DEFS.keys()))
    tools_stop = tools_sub.add_parser("stop", help="Stop a bundled tool.")
    tools_stop.add_argument("--tool", required=True, choices=sorted(TOOL_DEFS.keys()))
    tools_sub.add_parser("outputs", help="Show cached tool output tails.")

    return parser.parse_args(argv)


def _select_auth_refs(auth_refs):
    items = list_auth_files()
    item_map = {item.get("id"): item for item in items if item.get("id")}
    selected_items = []
    for auth_ref in auth_refs:
        item = item_map.get(str(auth_ref or "").strip())
        if item and item not in selected_items:
            selected_items.append(item)

    state = load_state()
    state["selected_auth"] = selected_items[0].get("name") if selected_items else None
    state["selected_auth_ref"] = selected_items[0].get("id") if selected_items else None
    state["selected_auths"] = [item.get("name") for item in selected_items]
    state["selected_auth_refs"] = [item.get("id") for item in selected_items]
    save_state(state)
    return {
        "ok": True,
        "selected_auth": state["selected_auth"],
        "selected_auth_ref": state["selected_auth_ref"],
        "selected_auths": state["selected_auths"],
        "selected_auth_refs": state["selected_auth_refs"],
        "count": len(selected_items),
    }


def _handle_auth(args):
    if args.auth_command == "list":
        items = list_auth_files()
        provider = str(args.provider or "").strip().lower()
        source = str(args.source or "").strip().lower()
        filtered = []
        for item in items:
            if provider and str(item.get("provider") or "").strip().lower() != provider:
                continue
            if source and str(item.get("sourceId") or "").strip().lower() != source:
                continue
            if args.manual_only and not bool(item.get("manual")):
                continue
            filtered.append(item)
        return {"ok": True, "items": filtered, "count": len(filtered)}

    if args.auth_command == "select":
        return _select_auth_refs(args.ids)

    if args.auth_command == "clear":
        return _select_auth_refs([])

    if args.auth_command == "delete":
        return {"ok": True, **delete_auth_entries(args.ids)}

    if args.auth_command == "create-manual":
        item = create_manual_auth_entry(
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            provider=args.provider,
            remark=args.remark,
        )
        return {"ok": True, "item": item}

    raise ValueError(f"Unknown auth command: {args.auth_command}")


def _handle_proxy(args):
    if args.proxy_command == "start":
        return start_proxy()
    if args.proxy_command == "stop":
        return stop_proxy()
    if args.proxy_command == "restart":
        return restart_proxy()
    if args.proxy_command == "query-models":
        return query_models()
    if args.proxy_command == "test":
        return test_proxy()
    raise ValueError(f"Unknown proxy command: {args.proxy_command}")


def _handle_runtime(args):
    if args.runtime_command == "rebuild":
        return rebuild_runtime_config_from_state(load_state())
    raise ValueError(f"Unknown runtime command: {args.runtime_command}")


def _handle_models(args):
    if args.models_command == "provider":
        items = get_configured_provider_models()
        if args.runtime:
            runtime_state = get_provider_model_test_state()
            return {"ok": True, "items": items, "runtime_test_state": runtime_state}
        return {"ok": True, "items": items}
    if args.models_command == "aggregate":
        return {"ok": True, "items": get_configured_aggregate_models()}
    if args.models_command == "provider-test-state":
        return get_provider_model_test_state()
    raise ValueError(f"Unknown models command: {args.models_command}")


def _handle_audit(args):
    if args.audit_command == "security":
        return {"ok": True, "report": generate_security_report(include_paths=args.include_paths)}
    raise ValueError(f"Unknown audit command: {args.audit_command}")


def _handle_tools(args):
    if args.tools_command == "list":
        outputs = get_tool_outputs()
        items = []
        for tool_id, meta in TOOL_DEFS.items():
            state = (outputs.get("states") or {}).get(tool_id, {})
            items.append(
                {
                    "id": tool_id,
                    "description": meta.get("desc"),
                    "running": bool((outputs.get("running") or {}).get(tool_id)),
                    "pid": state.get("pid"),
                    "returncode": state.get("returncode"),
                    "error": state.get("error"),
                }
            )
        return {"ok": True, "items": items}
    if args.tools_command == "run":
        return run_tool(args.tool)
    if args.tools_command == "stop":
        return stop_tool(args.tool)
    if args.tools_command == "outputs":
        return {"ok": True, **get_tool_outputs()}
    raise ValueError(f"Unknown tools command: {args.tools_command}")


def dispatch(args):
    if args.command == "status":
        return {"ok": True, "status": _redact_status(current_status(), include_logs=args.include_logs)}
    if args.command == "state":
        state = load_state()
        if not args.include_secrets:
            state = _redact_mapping(state)
        return {"ok": True, "state": state}
    if args.command == "auth":
        return _handle_auth(args)
    if args.command == "proxy":
        return _handle_proxy(args)
    if args.command == "runtime":
        return _handle_runtime(args)
    if args.command == "audit":
        return _handle_audit(args)
    if args.command == "models":
        return _handle_models(args)
    if args.command == "tools":
        return _handle_tools(args)
    raise ValueError(f"Unknown command: {args.command}")


def main(argv=None):
    args = _parse_args(argv)
    try:
        result = dispatch(args)
    except Exception as exc:
        _print_json({"ok": False, "error": str(exc)}, compact=args.compact)
        return 1
    _print_json(result, compact=args.compact)
    return 0 if bool(result.get("ok", True)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
