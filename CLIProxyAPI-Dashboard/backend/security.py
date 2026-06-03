import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from backend.api_keys import list_api_keys
from backend.auth import (
    _extract_manual_api_config,
    _read_auth_payload,
    list_auth_files,
    resolve_auth_reference,
)
from backend.paths import (
    DEVICE_LOGIN_STDERR,
    DEVICE_LOGIN_STDOUT,
    PROXY_STDERR,
    PROXY_STDOUT,
    STATE_FILE,
    TOOL_LOGS_DIR,
)
from backend.processes import current_status
from backend.state import get_proxy_api_key, load_state


_SECRET_PATTERNS = (
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9._=-]{16,}", re.IGNORECASE)),
    ("api_key_field", re.compile(r'"api[_-]?key"\s*:\s*"[^"]{8,}"', re.IGNORECASE)),
    ("token_field", re.compile(r'"(?:access|refresh|session|id)[_-]?token"\s*:\s*"[^"]{8,}"', re.IGNORECASE)),
)


def _normalize_host(value: str) -> str:
    return str(value or "").strip().lower()


def _is_loopback_host(value: str) -> bool:
    host = _normalize_host(value)
    return host in {"", "127.0.0.1", "localhost", "::1"}


def _severity_rank(severity: str) -> int:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    return order.get(str(severity or "").strip().lower(), 99)


def _add_finding(findings: list[dict], severity: str, area: str, title: str, detail: str, recommendation: str, evidence=None):
    findings.append(
        {
            "severity": severity,
            "area": area,
            "title": title,
            "detail": detail,
            "recommendation": recommendation,
            "evidence": list(evidence or []),
        }
    )


def _read_text_sample(path: Path, max_bytes: int = 120_000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _scan_file_for_secret_patterns(path: Path) -> list[str]:
    sample = _read_text_sample(path)
    if not sample:
        return []
    matches = []
    for pattern_name, pattern in _SECRET_PATTERNS:
        if pattern.search(sample):
            matches.append(pattern_name)
    return matches


def _collect_manual_auth_metadata(items: list[dict]) -> list[dict]:
    entries = []
    for item in items:
        auth_ref = item.get("id")
        if not item.get("manual") or not auth_ref:
            continue
        resolved = resolve_auth_reference(auth_ref=auth_ref)
        if not resolved:
            continue
        _, path = resolved
        payload = _read_auth_payload(path)
        manual_config = _extract_manual_api_config(payload, path.name)
        if not manual_config:
            continue
        entry = {
            "id": auth_ref,
            "provider": manual_config.get("provider") or item.get("provider") or "unknown",
            "base_url": manual_config.get("base_url") or "",
            "models": manual_config.get("models") or [],
            "path": str(path),
        }
        entries.append(entry)
    return entries


def generate_security_report(*, include_paths: bool = False) -> dict:
    now = int(time.time())
    state = load_state()
    status = current_status()
    auth_items = list_auth_files()
    api_keys = list_api_keys()
    findings: list[dict] = []

    dashboard_host = os.environ.get("CLIPROXYAPI_DASHBOARD_HOST", "127.0.0.1")
    proxy_api_key = get_proxy_api_key(state)
    selected_refs = [str(value).strip() for value in (state.get("selected_auth_refs") or []) if str(value).strip()]
    applied_refs = [str(value).strip() for value in (state.get("applied_auth_refs") or []) if str(value).strip()]
    item_ids = {item.get("id") for item in auth_items if item.get("id")}

    if not _is_loopback_host(dashboard_host):
        _add_finding(
            findings,
            "critical",
            "runtime",
            "Dashboard host is not loopback-only",
            f"The dashboard binds to {dashboard_host}, so every management route becomes reachable beyond the local machine.",
            "Bind the dashboard to 127.0.0.1 or put it behind a trusted local tunnel with its own authentication boundary.",
            [f"dashboard_host={dashboard_host}"],
        )

    if state.get("exposure_enabled"):
        severity = "critical" if status.get("proxy_running") else "high"
        detail = "RelayX exposure mode is enabled, so the proxy is intended for LAN or wider access."
        recommendation = "Disable exposure mode when not actively needed, or rotate the admin key and front the proxy with a stronger access layer."
        evidence = [f"exposure_url={status.get('exposure_url') or '-'}", f"bind_host={status.get('bind_host') or '-'}"]
        _add_finding(findings, severity, "runtime", "Proxy exposure mode is enabled", detail, recommendation, evidence)

    if not state.get("exposure_enabled") and proxy_api_key == "cliproxyapi":
        _add_finding(
            findings,
            "medium",
            "runtime",
            "Proxy still uses the default admin API key",
            "The proxy admin key remains the default local value `cliproxyapi`.",
            "Keep this only for loopback-only development. For any shared environment, rotate to a random admin key before use.",
            ["api_key_mode=default-local"],
        )

    if state.get("exposure_enabled") and proxy_api_key == "cliproxyapi":
        _add_finding(
            findings,
            "critical",
            "runtime",
            "Exposed proxy is using the default admin API key",
            "Exposure mode and the default admin API key are enabled at the same time.",
            "Disable exposure immediately or rotate the proxy admin key before bringing the service back online.",
            ["api_key_mode=default-local"],
        )

    _ = selected_refs
    _ = applied_refs
    _ = item_ids

    manual_entries = _collect_manual_auth_metadata(auth_items)
    if manual_entries:
        _add_finding(
            findings,
            "high",
            "auth",
            "Manual API-key auth entries are stored on disk",
            f"{len(manual_entries)} manual auth entr{'y' if len(manual_entries) == 1 else 'ies'} store upstream credentials in local JSON files.",
            "Restrict filesystem access to the storage directory and prefer rotating manual keys more aggressively than OAuth-derived credentials.",
            [entry["id"] for entry in manual_entries[:8]],
        )

    insecure_manual_urls = []
    custom_manual_providers = []
    for entry in manual_entries:
        base_url = str(entry.get("base_url") or "").strip()
        parsed = urlparse(base_url)
        scheme = (parsed.scheme or "").lower()
        provider = str(entry.get("provider") or "").strip().lower()
        if scheme and scheme != "https":
            insecure_manual_urls.append(entry)
        if provider in {"custom", "unknown", ""}:
            custom_manual_providers.append(entry)
    if insecure_manual_urls:
        _add_finding(
            findings,
            "critical",
            "provider",
            "Manual provider entries include non-HTTPS upstream URLs",
            "At least one manual auth entry points to an upstream base URL that is not HTTPS.",
            "Move those providers behind HTTPS before using them for any real traffic.",
            [entry["id"] for entry in insecure_manual_urls[:8]],
        )
    if custom_manual_providers:
        _add_finding(
            findings,
            "medium",
            "provider",
            "Some manual entries use unclassified providers",
            "Several manual auth entries could not be mapped to a known provider family.",
            "Review those entries to confirm protocol compatibility, model naming, and credential scope before relying on them in aggregates.",
            [entry["id"] for entry in custom_manual_providers[:8]],
        )

    active_virtual_keys = [item for item in api_keys if item.get("enabled") and not item.get("expired")]
    if state.get("exposure_enabled") and not active_virtual_keys:
        _add_finding(
            findings,
            "high",
            "runtime",
            "Exposure mode is enabled without any scoped virtual keys",
            "The service is exposed, but there are no active downstream virtual keys to separate user access from the admin key.",
            "Create scoped virtual keys for consumers and keep the admin key for maintenance only.",
            ["virtual_keys_active=0"],
        )

    for key in active_virtual_keys:
        key_name = str(key.get("name") or key.get("id") or "").strip() or "unnamed"
        if not key.get("allowed_models"):
            _add_finding(
                findings,
                "medium",
                "runtime",
                "Virtual key has unrestricted model access",
                f"Virtual key `{key_name}` can access every model routed through RelayX.",
                "Set allowed model lists for keys that are meant for a specific tenant, workload, or budget class.",
                [f"virtual_key={key_name}"],
            )
        if not int(key.get("max_requests") or 0) and not int(key.get("max_tokens") or 0):
            _add_finding(
                findings,
                "low",
                "runtime",
                "Virtual key has no quota guardrails",
                f"Virtual key `{key_name}` has neither a request cap nor a token cap.",
                "Add at least one quota guardrail for shared or externally distributed keys.",
                [f"virtual_key={key_name}"],
            )

    log_files = [DEVICE_LOGIN_STDOUT, DEVICE_LOGIN_STDERR, PROXY_STDOUT, PROXY_STDERR]
    if TOOL_LOGS_DIR.exists():
        log_files.extend(sorted(path for path in TOOL_LOGS_DIR.glob("*.log") if path.is_file()))
    leaked_logs = []
    for path in log_files:
        matches = _scan_file_for_secret_patterns(path)
        if matches:
            leaked_logs.append({"path": path, "matches": matches})
    if leaked_logs:
        _add_finding(
            findings,
            "critical",
            "logs",
            "Logs contain values that look like live credentials",
            f"{len(leaked_logs)} log file(s) matched credential-like patterns.",
            "Rotate any exposed secrets, trim or delete the affected logs, and add stronger redaction before collecting new diagnostics.",
            [
                f"{entry['path'].name}:{','.join(entry['matches'])}" if not include_paths else f"{entry['path']}:{','.join(entry['matches'])}"
                for entry in leaked_logs[:10]
            ],
        )

    if STATE_FILE.exists():
        state_matches = _scan_file_for_secret_patterns(STATE_FILE)
        if state_matches:
            _add_finding(
                findings,
                "high",
                "auth",
                "Persisted state file contains raw secret patterns",
                "The runtime state file contains values that match credential-like patterns.",
                "Keep the state directory protected and avoid sharing backups without scrubbing secrets first.",
                [STATE_FILE.name if not include_paths else str(STATE_FILE), f"patterns={','.join(state_matches)}"],
            )

    findings.sort(key=lambda item: (_severity_rank(item.get("severity")), item.get("area"), item.get("title")))
    counts = {name: 0 for name in ("critical", "high", "medium", "low", "info")}
    for finding in findings:
        counts[str(finding.get("severity") or "info")] = counts.get(str(finding.get("severity") or "info"), 0) + 1

    total = len(findings)
    if counts["critical"]:
        posture = "critical"
    elif counts["high"]:
        posture = "elevated"
    elif counts["medium"]:
        posture = "watch"
    else:
        posture = "stable"

    score = max(0, 100 - counts["critical"] * 25 - counts["high"] * 12 - counts["medium"] * 5 - counts["low"] * 2)
    return {
        "generated_at": now,
        "summary": {
            "posture": posture,
            "score": score,
            "total_findings": total,
            **counts,
        },
        "areas": {
            "auth": {
                "total_auth_files": len(auth_items),
                "manual_entries": len(manual_entries),
                "selected_auth_refs": len(selected_refs),
                "applied_auth_refs": len(applied_refs),
            },
            "providers": {
                "manual_custom_providers": len(custom_manual_providers),
                "manual_non_https_base_urls": len(insecure_manual_urls),
            },
            "runtime": {
                "dashboard_host": dashboard_host,
                "proxy_running": bool(status.get("proxy_running")),
                "exposure_enabled": bool(state.get("exposure_enabled")),
                "bind_host": status.get("bind_host"),
                "exposure_url": status.get("exposure_url"),
                "virtual_keys_active": len(active_virtual_keys),
            },
            "logs": {
                "scanned_files": len(log_files),
                "suspicious_files": len(leaked_logs),
            },
        },
        "findings": findings,
    }
