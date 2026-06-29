import json
import shutil
import base64
from datetime import datetime
from pathlib import Path

from backend.paths import (
    STORAGE_DIR, CONFIG_DIR, AUTH_DIR, AUTH_ARCHIVE_DIR,
    MODELS_DIR, RUNTIME_DIR, CACHE_DIR, BACKUPS_DIR,
    STATE_FILE, BASE_CONFIG, SOURCES_CONFIG_FILE,
)
from backend.api_keys import _load_keys, _save_keys, API_KEYS_FILE
from backend.state import load_state, save_state
from backend.auth import list_auth_files, _read_auth_payload

EXPORT_VERSION = 1


def _read_json_file(path: Path) -> dict | list | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def _collect_auth_entries() -> list[dict]:
    items = []
    for auth_file in list_auth_files():
        source = auth_file.get('source_path')
        if not source or not Path(source).exists():
            continue
        try:
            payload = _read_auth_payload(Path(source))
        except Exception:
            payload = None
        items.append({
            'id': auth_file.get('id'),
            'name': auth_file.get('name'),
            'provider': auth_file.get('provider'),
            'filename': Path(source).name,
            'payload': payload,
        })
    return items


def export_all() -> dict:
    state = load_state()
    api_keys = _load_keys()

    return {
        'ok': True,
        'version': EXPORT_VERSION,
        'exported_at': datetime.now().isoformat(timespec='seconds'),
        'state': state,
        'api_keys': api_keys,
        'auth_entries': _collect_auth_entries(),
        'base_config': BASE_CONFIG.read_text(encoding='utf-8') if BASE_CONFIG.exists() else None,
        'sources_config': _read_json_file(SOURCES_CONFIG_FILE),
        'model_overrides': _read_json_file(MODELS_DIR / 'provider_model_overrides.json'),
        'aggregate_aliases': _read_json_file(MODELS_DIR / 'aggregate_model_aliases.json'),
        'model_test_state': _read_json_file(MODELS_DIR / 'provider_model_test_state.json'),
        'model_proxy_settings': _read_json_file(MODELS_DIR / 'model_proxy_settings.json'),
    }


def import_all(payload: dict, *, mode: str = 'merge') -> dict:
    if not isinstance(payload, dict):
        return {'ok': False, 'message': 'Invalid import data format.'}

    version = payload.get('version')
    if not version:
        return {'ok': False, 'message': 'Missing version in import data.'}

    imported = []
    errors = []

    if mode == 'replace':
        _clear_importable_data()
        imported.append('cleared existing data')

    state = payload.get('state')
    if isinstance(state, dict):
        try:
            current = load_state() if mode == 'merge' else {}
            current.update(state)
            save_state(current)
            imported.append('state')
        except Exception as e:
            errors.append(f'state: {e}')

    api_keys = payload.get('api_keys')
    if isinstance(api_keys, list):
        try:
            if mode == 'replace':
                _save_keys(api_keys)
            else:
                existing = _load_keys()
                existing_map = {k.get('value'): k for k in existing}
                for key in api_keys:
                    val = key.get('value')
                    if val and val not in existing_map:
                        existing.append(key)
                _save_keys(existing)
            imported.append(f'{len(api_keys)} api_keys')
        except Exception as e:
            errors.append(f'api_keys: {e}')

    auth_entries = payload.get('auth_entries')
    if isinstance(auth_entries, list):
        restored = 0
        for entry in auth_entries:
            payload_data = entry.get('payload')
            filename = entry.get('filename')
            if not payload_data or not filename:
                continue
            try:
                target = AUTH_DIR / filename
                if target.exists() and mode == 'merge':
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(payload_data, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                restored += 1
            except Exception as e:
                errors.append(f'auth {filename}: {e}')
        if restored:
            imported.append(f'{restored} auth_entries')

    base_config = payload.get('base_config')
    if isinstance(base_config, str) and base_config.strip():
        try:
            if not BASE_CONFIG.exists() or mode == 'replace':
                BASE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
                BASE_CONFIG.write_text(base_config, encoding='utf-8')
                imported.append('base_config')
        except Exception as e:
            errors.append(f'base_config: {e}')

    sources_config = payload.get('sources_config')
    if isinstance(sources_config, dict):
        try:
            if not SOURCES_CONFIG_FILE.exists() or mode == 'replace':
                SOURCES_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                SOURCES_CONFIG_FILE.write_text(
                    json.dumps(sources_config, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                imported.append('sources_config')
        except Exception as e:
            errors.append(f'sources_config: {e}')

    for key, filename in [
        ('model_overrides', 'provider_model_overrides.json'),
        ('aggregate_aliases', 'aggregate_model_aliases.json'),
        ('model_test_state', 'provider_model_test_state.json'),
        ('model_proxy_settings', 'model_proxy_settings.json'),
    ]:
        data = payload.get(key)
        if isinstance(data, (dict, list)):
            try:
                target = MODELS_DIR / filename
                if not target.exists() or mode == 'replace':
                    MODELS_DIR.mkdir(parents=True, exist_ok=True)
                    target.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding='utf-8',
                    )
                    imported.append(key)
            except Exception as e:
                errors.append(f'{key}: {e}')

    return {
        'ok': len(errors) == 0,
        'imported': imported,
        'errors': errors,
        'message': f'Imported {len(imported)} items.' + (f' {len(errors)} errors.' if errors else ''),
    }


def _clear_importable_data():
    for f in AUTH_DIR.glob('*.json'):
        try:
            f.unlink()
        except Exception:
            pass

    for sub in AUTH_DIR.iterdir():
        if sub.is_dir() and sub.name.lower() not in ('archive', 'backups', 'logs'):
            try:
                shutil.rmtree(sub)
            except Exception:
                pass

    state_file = RUNTIME_DIR / 'state.json'
    if state_file.exists():
        try:
            state_file.write_text('{}', encoding='utf-8')
        except Exception:
            pass

    if API_KEYS_FILE.exists():
        try:
            _save_keys([])
        except Exception:
            pass

    for filename in [
        'provider_model_overrides.json',
        'aggregate_model_aliases.json',
        'provider_model_test_state.json',
        'model_proxy_settings.json',
    ]:
        target = MODELS_DIR / filename
        if target.exists():
            try:
                target.unlink()
            except Exception:
                pass
