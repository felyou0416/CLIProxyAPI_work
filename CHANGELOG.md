# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

