"""
Settings API module - handles settings, version info, and update checks.
"""
import json
import os
import subprocess
from pathlib import Path
from datetime import datetime

from backend.paths import STATE_FILE, ROOT, PROXY_ROOT


def _load_settings():
    """Load settings from state.json or create defaults."""
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass

    defaults = {
        'autostart': False,
        # Desktop shell default: close (X) hides to tray; Settings can turn this off.
        'minimize_tray': True,
        'language': 'zh',
        'theme': 'dark',
        'auto_update_check': True,
        'update_channel': 'stable',
    }

    # Merge defaults with loaded state
    for key, value in defaults.items():
        if key not in state:
            state[key] = value

    return state


def get_settings():
    """Get all settings. Reflect real Windows autostart install state."""
    item = _load_settings()
    if os.name == 'nt':
        try:
            from backend.autostart import get_autostart_status
            status = get_autostart_status()
            item['autostart'] = bool(status.get('installed'))
            item['autostart_path'] = status.get('path') or ''
        except Exception:
            item.setdefault('autostart_path', '')
    return {'ok': True, 'item': item}


def save_setting(key, value):
    """Save a single setting. autostart also installs/removes Startup launcher."""
    state = _load_settings()
    key = str(key or '').strip()
    if not key:
        return {'ok': False, 'message': 'Missing setting key'}

    applied = None
    if key == 'autostart':
        enabled = value in (True, 1, '1', 'true', 'True', 'yes', 'on')
        value = enabled
        try:
            from backend.autostart import apply_autostart
            applied = apply_autostart(enabled)
            if not applied.get('ok'):
                return {
                    'ok': False,
                    'message': applied.get('message') or 'Failed to update Windows autostart',
                    'autostart': applied,
                }
            # Trust the real install state after apply.
            value = bool(applied.get('installed')) if enabled else False
        except Exception as exc:
            return {'ok': False, 'message': f'Failed to update Windows autostart: {exc}'}

    state[key] = value

    # Save back to state file
    try:
        temp_path = STATE_FILE.with_suffix('.tmp')
        temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        temp_path.replace(STATE_FILE)
        result = {'ok': True, 'message': f'Setting {key} saved', 'value': value}
        if applied is not None:
            result['autostart'] = applied
            result['message'] = applied.get('message') or result['message']
        return result
    except Exception as e:
        return {'ok': False, 'message': str(e)}


def get_version_info():
    """Get version information for all components."""
    version_file = ROOT / 'VERSION'
    cli_version_file = PROXY_ROOT / 'VERSION' if PROXY_ROOT else None

    current_version = '0.0.0'
    build_date = datetime.now().strftime('%Y-%m-%d')

    if version_file.exists():
        try:
            current_version = version_file.read_text(encoding='utf-8').strip()
        except Exception:
            pass

    if not current_version or current_version == '0.0.0':
        current_version = '1.0.0'

    cli_version = current_version
    if cli_version_file and cli_version_file.exists():
        try:
            cli_version = cli_version_file.read_text(encoding='utf-8').strip()
        except Exception:
            pass

    return {
        'ok': True,
        'item': {
            'version': current_version,
            'cli_version': cli_version,
            'dashboard_version': current_version,
            'desktop_version': current_version,
            # Kept for older Dashboard Web UI builds that still read this field.
            'electron_version': current_version,
            'build_date': build_date,
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    }


def check_for_updates():
    """Check for updates on GitHub."""
    import urllib.request
    import ssl

    current_version = '1.0.0'
    version_file = ROOT / 'VERSION'
    if version_file.exists():
        try:
            current_version = version_file.read_text(encoding='utf-8').strip()
        except Exception:
            pass

    # Try to get latest release from GitHub
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            'https://api.github.com/repos/youqu117/CLIProxyAPI_work/releases/latest',
            headers={'User-Agent': 'CLIProxyAPI-Checker'}
        )
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            data = json.loads(response.read().decode('utf-8'))
            latest_tag = data.get('tag_name', 'v1.0.0').lstrip('v')
            return {
                'ok': True,
                'item': {
                    'current_version': current_version,
                    'latest_version': latest_tag,
                    'update_available': latest_tag != current_version,
                    'release_url': data.get('html_url', ''),
                    'published_at': data.get('published_at', ''),
                }
            }
    except Exception as e:
        return {
            'ok': True,
            'item': {
                'current_version': current_version,
                'latest_version': current_version,
                'update_available': False,
                'error': str(e),
            }
        }


def download_update():
    """Download the latest release zip from GitHub to the user's Downloads folder in background."""
    import urllib.request
    import ssl
    from pathlib import Path
    
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        # Get latest release data
        req = urllib.request.Request(
            'https://api.github.com/repos/youqu117/CLIProxyAPI_work/releases/latest',
            headers={'User-Agent': 'CLIProxyAPI-Checker'}
        )
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        # Try to find a Windows asset first, or fallback to zipball_url
        download_url = None
        filename = "cliproxyapi-update.zip"
        
        assets = data.get('assets', [])
        for asset in assets:
            name = asset.get('name', '')
            if name.endswith('.zip') or name.endswith('.exe'):
                download_url = asset.get('browser_download_url')
                filename = name
                break
                
        if not download_url:
            download_url = data.get('zipball_url')
            filename = f"cliproxyapi-source-{data.get('tag_name', 'latest')}.zip"
            
        if not download_url:
            return {'ok': False, 'message': 'No download URL found.'}
            
        import threading
        
        def do_download(url, fn):
            try:
                # Save to user's downloads folder or current folder
                save_dir = Path.home() / 'Downloads'
                if not save_dir.exists():
                    save_dir = Path('.')
                target_path = save_dir / fn
                
                req_dl = urllib.request.Request(url, headers={'User-Agent': 'CLIProxyAPI-Downloader'})
                with urllib.request.urlopen(req_dl, timeout=120, context=ctx) as dl_response:
                    target_path.write_bytes(dl_response.read())
            except Exception as e:
                print(f"Download thread failed: {e}")
                
        threading.Thread(target=do_download, args=(download_url, filename), daemon=True).start()
        
        return {'ok': True, 'message': f'Downloading {filename} to your Downloads directory in background.'}
    except Exception as e:
        return {'ok': False, 'message': f'Failed to initiate download: {e}'}

