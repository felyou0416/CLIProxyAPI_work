"""Windows logon autostart for the Dashboard control panel."""

from __future__ import annotations

import os
from pathlib import Path


SHORTCUT_NAME = 'CLIProxyAPI Dashboard.cmd'
LEGACY_SHORTCUT_NAME = 'CLIProxyAPI Dashboard.lnk'


def _dashboard_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _startup_dir() -> Path:
    appdata = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
    return Path(appdata) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'


def startup_cmd_path() -> Path:
    return _startup_dir() / SHORTCUT_NAME


def legacy_shortcut_path() -> Path:
    return _startup_dir() / LEGACY_SHORTCUT_NAME


def is_autostart_installed() -> bool:
    return startup_cmd_path().is_file() or legacy_shortcut_path().is_file()


def _build_startup_cmd(open_browser: bool = False) -> str:
    root = _dashboard_root()
    ps1 = root / 'start_dashboard.ps1'
    open_flag = ' -OpenBrowser' if open_browser else ''
    # Delayed start: at logon, PATH / network / proxy clients may not be ready yet.
    # Log everything so silent failures are diagnosable after reboot.
    return (
        '@echo off\r\n'
        'setlocal\r\n'
        f'set "DASHBOARD_ROOT={root}"\r\n'
        'set "LOG_DIR=%DASHBOARD_ROOT%\\..\\CLIProxyAPI\\storage\\logs"\r\n'
        'if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1\r\n'
        'set "LOG_FILE=%LOG_DIR%\\dashboard.autostart.log"\r\n'
        'echo ===== %DATE% %TIME% autostart begin =====>>"%LOG_FILE%"\r\n'
        'rem Wait for desktop / user profile / PATH to settle after logon.\r\n'
        'timeout /t 12 /nobreak >nul\r\n'
        'cd /d "%DASHBOARD_ROOT%" >>"%LOG_FILE%" 2>&1\r\n'
        f'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
        f'-File "%DASHBOARD_ROOT%\\start_dashboard.ps1"{open_flag} >>"%LOG_FILE%" 2>&1\r\n'
        'echo exit_code=%ERRORLEVEL%>>"%LOG_FILE%"\r\n'
        'echo ===== %DATE% %TIME% autostart end =====>>"%LOG_FILE%"\r\n'
        'endlocal\r\n'
    )


def install_autostart(open_browser: bool = False) -> dict:
    """Install a Startup folder launcher. Returns status payload."""
    if os.name != 'nt':
        return {
            'ok': False,
            'installed': False,
            'message': 'Autostart is only supported on Windows.',
            'path': '',
        }

    startup = _startup_dir()
    try:
        startup.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {
            'ok': False,
            'installed': False,
            'message': f'Cannot create Startup folder: {exc}',
            'path': str(startup_cmd_path()),
        }

    ps1 = _dashboard_root() / 'start_dashboard.ps1'
    if not ps1.is_file():
        return {
            'ok': False,
            'installed': False,
            'message': f'start_dashboard.ps1 not found: {ps1}',
            'path': str(startup_cmd_path()),
        }

    target = startup_cmd_path()
    try:
        target.write_text(_build_startup_cmd(open_browser=open_browser), encoding='utf-8')
    except Exception as exc:
        return {
            'ok': False,
            'installed': False,
            'message': f'Failed to write Startup launcher: {exc}',
            'path': str(target),
        }

    # Prefer the cmd launcher; remove the older silent .lnk if present.
    legacy = legacy_shortcut_path()
    if legacy.is_file():
        try:
            legacy.unlink()
        except Exception:
            pass

    return {
        'ok': True,
        'installed': True,
        'message': f'Installed Windows autostart launcher: {target}',
        'path': str(target),
    }


def uninstall_autostart() -> dict:
    """Remove Startup folder launcher(s)."""
    removed = []
    errors = []
    for path in (startup_cmd_path(), legacy_shortcut_path()):
        if not path.is_file():
            continue
        try:
            path.unlink()
            removed.append(str(path))
        except Exception as exc:
            errors.append(f'{path}: {exc}')

    if errors:
        return {
            'ok': False,
            'installed': is_autostart_installed(),
            'message': '; '.join(errors),
            'removed': removed,
            'path': str(startup_cmd_path()),
        }

    if removed:
        return {
            'ok': True,
            'installed': False,
            'message': 'Removed Windows autostart launcher.',
            'removed': removed,
            'path': str(startup_cmd_path()),
        }

    return {
        'ok': True,
        'installed': False,
        'message': 'Windows autostart launcher was not installed.',
        'removed': [],
        'path': str(startup_cmd_path()),
    }


def apply_autostart(enabled: bool, open_browser: bool = False) -> dict:
    if enabled:
        return install_autostart(open_browser=open_browser)
    return uninstall_autostart()


def get_autostart_status() -> dict:
    path = startup_cmd_path()
    legacy = legacy_shortcut_path()
    installed = path.is_file() or legacy.is_file()
    active_path = str(path if path.is_file() else (legacy if legacy.is_file() else path))
    return {
        'ok': True,
        'installed': installed,
        'path': active_path,
        'cmd_path': str(path),
        'legacy_path': str(legacy),
    }
