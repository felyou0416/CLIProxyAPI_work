import os
import platform
import shutil
from pathlib import Path


def is_windows() -> bool:
    return os.name == "nt" or platform.system().lower().startswith("win")


def _env_flag(name: str) -> str:
    return str(os.environ.get(name, "") or "").strip().lower()


def in_docker() -> bool:
    if _env_flag("RELAYX_RUNTIME_MODE") in {"docker", "container", "linux-docker"}:
        return True
    if Path("/.dockerenv").exists():
        return True
    cgroup_path = Path("/proc/1/cgroup")
    if cgroup_path.exists():
        try:
            content = cgroup_path.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            content = ""
        if "docker" in content or "containerd" in content or "kubepods" in content:
            return True
    return False


def runtime_variant() -> str:
    if is_windows():
        return "windows"
    if in_docker():
        return "linux-docker"
    return "linux"


def dashboard_auto_start_enabled() -> bool:
    raw = _env_flag("CLIPROXYAPI_AUTO_START")
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return is_windows()


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _cli_binary_name() -> str:
    return "cli-proxy-api.exe" if is_windows() else "cli-proxy-api"


def resolve_cli_binary(proxy_root: Path) -> Path:
    override = str(os.environ.get("RELAYX_CLI_BINARY", "") or "").strip()
    if override:
        return Path(override).expanduser()

    binary_name = _cli_binary_name()
    candidates: list[Path] = [
        proxy_root / "CLIProxyAPI" / "bin" / binary_name,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def cli_binary_hint() -> str:
    if is_windows():
        return (
            "Set CLIPROXYAPI_ROOT to the proxy repo, then run "
            "CLIProxyAPI\\scripts\\build-proxy.ps1. "
            "Or set RELAYX_CLI_BINARY to a custom path."
        )
    if in_docker():
        return "Set RELAYX_CLI_BINARY to the Linux CLIProxyAPI binary path."
    return "Build CLIProxyAPI/bin/cli-proxy-api or set RELAYX_CLI_BINARY."
