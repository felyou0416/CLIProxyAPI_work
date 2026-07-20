# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.6] - 2026-07-20
### Added
- create-grok control-station service (start/restart/stop) with status indicator on port 3780.
- Historical model-stats provider attribution, including deleted mappings labeled as residual history.
- Forced observability cache refresh that waits for in-flight rebuilds, then rescans logs once more.
- Mobile safe-area insets and additional lite-shell polish for narrow viewports.

### Fixed
- Dashboard restart race: exit current process first, then detach relauncher with cooldown stamp.
- Requests refresh button no longer returns stale cache during an active observability rebuild.
- Boot double-reload loops; hard reload only when the server version changes.
- Static asset serving and lazy-loading of heavy frontend assets to reduce first-paint lag.

### Changed
- Control-station config gains create-grok alongside OAuth/OpenClaw service cards.
- Request metrics summary and model-stats panels surface historical-only models more clearly.

## [1.0.5] - 2026-07-18
### Added
- Windows logon autostart via Startup folder `.cmd` launcher, wired from Settings.
- System proxy controls on the account control station (port presets, detect, toggle, reset).
- Mobile navigation drawer, filter-rail drawers, and chat session/media drawers for narrow screens.
- Config-driven control-station layers with per-group busy locks and short action labels.

### Fixed
- Boot autostart reliability: resolve Python at logon, wait for PATH settle, write autostart logs.
- Non-blocking cold start: accept HTTP first, start RelayX in background so health checks do not time out.
- Electron close/tray UX: close-to-tray without dialog, single-instance guard, window state restore.
- Chat mobile session drawer height crush and Thinking/provider overflow on small viewports.

### Changed
- Slim dashboard shell: full-bleed panels, sidebar retune, hide low-frequency access entries behind system center.
- Package build includes `backend.settings` hiddenimport for packaged Settings endpoints.

## [1.0.4] - 2026-07-16
### Added
- Auto-detect local mixed-port proxy (FlClash / MaoMao / Clash Verge) into runtime `proxy-url`.
- Force loopback providers to `proxy-url: direct` to avoid global proxy hijacking.
- Unified restart controls for OAuth manager, Cloudflare tunnel, Grok2API frontend/backend, and IP Helper.
- Split Grok2API frontend/backend status indicators with localStorage cache.

### Fixed
- OAuth manager start via PID/port detect and status polling.
- Auto-start media proxy with relay; prefer local MediaProxy `config.json`.
- xAI account profile export recognition and OAuth model exposure through dashboard.
- Provider mapping deletion, including default model mappings.
- Dashboard control-station indicator/button state sync during concurrent actions.

### Changed
- Chat UI redesigned with Chat/Image/Video mode pills and slide-out sessions.
- Ignore local `CLIProxyAPI-MediaProxy/config.json`; keep example tracked.

## [1.0.3] - 2026-07-02
### Added
- Added geometric minimalist app icon (`icon.png`, `icon.ico`) for Windows installer and desktop shortcut.

## [1.0.2] - 2026-07-02
### Fixed
- Fixed data loss on application update by migrating storage directory from installation directory (`resources/storage`) to system user data directory (`%APPDATA%/cliproxyapi-dashboard/storage`) in [main.js](file:///e:/U_App/CLIProxyAPI_work/electron-app/main.js).
- Added `CLIPROXYAPI_STORAGE_DIR` environment variable support in [paths.py](file:///e:/U_App/CLIProxyAPI_work/CLIProxyAPI-Dashboard/backend/paths.py) for flexible storage path configuration.

### Changed
- Optimized agent configuration files (`AGENTS.md`, `.claude/CLAUDE.md`) to reduce token consumption during conversation initialization.
- Added runtime state directories (`.omx/`, `.claude/worktrees/`) to `.gitignore` to prevent tracking temporary files.

## [1.0.1] - 2026-07-01
### Added
- Integrated full localization (Chinese/English) support for all settings page items in [i18n.js](file:///e:/U_App/CLIProxyAPI_work/CLIProxyAPI-Dashboard/js/i18n.js).
- Added `CHANGELOG.md` to track project release versions and modifications.
- Added a "Developer Options" category in the General settings panel, allowing users to clear local cache and reload the dashboard.
- Implemented `/api/download-update` endpoint in the Python backend [get_routes.py](file:///e:/U_App/CLIProxyAPI_work/CLIProxyAPI-Dashboard/backend/routes/get_routes.py) and [settings.py](file:///e:/U_App/CLIProxyAPI_work/CLIProxyAPI-Dashboard/backend/settings.py) to download release files in a background thread.
- Added startup update check in [boot.js](file:///e:/U_App/CLIProxyAPI_work/CLIProxyAPI-Dashboard/js/boot.js) using user settings.

### Fixed
- Extracted inline styles and scripts from `sections/settings.html` to dedicated [settings.css](file:///e:/U_App/CLIProxyAPI_work/CLIProxyAPI-Dashboard/css/panels/settings.css) and [settings.js](file:///e:/U_App/CLIProxyAPI_work/CLIProxyAPI-Dashboard/js/settings.js) files, fixing the bug where scripts and style sheets inside lazy-loaded HTML were ignored by the dashboard loader.
- Fixed the issue where settings (language, theme) saved on the settings panel did not apply to the local UI storage and document attributes immediately.
- Fixed the sidebar toggle buttons for language and theme to automatically sync change values to the backend server settings.

