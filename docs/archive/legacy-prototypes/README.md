# Archived Prototypes

These files are retained for historical reference only. They are not part of the supported runtime, build, or release paths.

- `proxy_manager.py` was a standalone Tk system-proxy utility. Dashboard now owns system proxy configuration through its supported API and UI.
- `auth-health-preview.html` and `system-runtime-entry.png` were standalone Dashboard UI experiments. Their relevant ideas were incorporated into the Dashboard; these artifacts are not loaded by the application.

Do not add new runtime code, user configuration, screenshots, logs, or shortcuts to the workspace root. Put user data under `CLIProxyAPI/storage/`, documentation under `docs/`, and application source under its owning component directory.
