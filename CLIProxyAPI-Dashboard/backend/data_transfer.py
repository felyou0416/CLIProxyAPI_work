import json
import shutil
from datetime import datetime
from pathlib import Path

from backend.paths import (
    AUTH_DIR, MODELS_DIR,
    STATE_FILE, BASE_CONFIG, SOURCES_CONFIG_FILE,
    RUNTIME_CONFIG,
)
from backend.api_keys import _load_keys, _save_keys, API_KEYS_FILE, API_KEYS_USAGE_FILE
from backend.state import load_state, save_state
from backend.auth import list_auth_files, _read_auth_payload

EXPORT_VERSION = 2


def _read_json_file(path: Path) -> dict | list | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def _read_text_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return None


def _collect_auth_entries() -> list[dict]:
    """Collect all auth entries with relative paths for correct import restore."""
    items = []
    seen = set()
    for auth_file in list_auth_files():
        # fix: use 'path' not 'source_path'
        source = auth_file.get('path')
        if not source or not Path(source).exists():
            continue
        source_path = Path(source)
        relative = auth_file.get('relativeName') or source_path.name
        dedup_key = relative.lower()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        try:
            payload = _read_auth_payload(source_path)
        except Exception:
            payload = None
        items.append({
            'id': auth_file.get('id'),
            'name': auth_file.get('name') or source_path.name,
            'provider': auth_file.get('provider'),
            'relative_name': relative,
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
        'data': {
            'state': state,
            'api_keys': api_keys,
            'auth_entries': _collect_auth_entries(),
            'base_config': _read_text_file(BASE_CONFIG),
            'runtime_config': _read_text_file(RUNTIME_CONFIG),
            'sources_config': _read_json_file(SOURCES_CONFIG_FILE),
            'model_overrides': _read_json_file(MODELS_DIR / 'provider_model_overrides.json'),
            'aggregate_aliases': _read_json_file(MODELS_DIR / 'aggregate_model_aliases.json'),
            'model_proxy_settings': _read_json_file(MODELS_DIR / 'model_proxy_settings.json'),
            'model_thinking_configs': _read_json_file(MODELS_DIR / 'model_thinking_configs.json'),
        },
    }


def import_all(payload: dict, *, mode: str = 'merge') -> dict:
    if not isinstance(payload, dict):
        return {'ok': False, 'message': 'Invalid import data format.'}

    version = payload.get('version')
    if not version:
        return {'ok': False, 'message': 'Missing version in import data.'}

    # Support both old format (top-level keys) and new format (under 'data')
    data = payload.get('data')
    if not isinstance(data, dict):
        # v1 format: keys at top level
        data = payload

    imported = []
    skipped = []
    errors = []

    if mode == 'replace':
        _clear_importable_data()
        imported.append('cleared existing data')

    # --- state ---
    state = data.get('state')
    if isinstance(state, dict):
        try:
            current = load_state() if mode == 'merge' else {}
            current.update(state)
            save_state(current)
            imported.append('state + settings')
        except Exception as e:
            errors.append(f'state: {e}')

    # --- api_keys (virtual keys) ---
    api_keys = data.get('api_keys')
    if isinstance(api_keys, list):
        try:
            if mode == 'replace':
                _save_keys(api_keys)
            else:
                existing = _load_keys()
                existing_ids = {str(k.get('id') or '') for k in existing}
                existing_keys = {str(k.get('key') or '') for k in existing}
                for key in api_keys:
                    kid = str(key.get('id') or '')
                    kval = str(key.get('key') or '')
                    if kid and kid in existing_ids:
                        continue
                    if kval and kval in existing_keys:
                        continue
                    existing.append(key)
                _save_keys(existing)
            imported.append(f'{len(api_keys)} api_keys')
        except Exception as e:
            errors.append(f'api_keys: {e}')

    # --- auth_entries ---
    auth_entries = data.get('auth_entries')
    if isinstance(auth_entries, list):
        restored = 0
        skipped_auth = 0
        for entry in auth_entries:
            payload_data = entry.get('payload')
            relative_name = entry.get('relative_name') or entry.get('filename') or ''
            if not payload_data or not relative_name:
                continue
            try:
                # Preserve provider subdirectory structure: agnes/xxx.json
                target = AUTH_DIR / relative_name
                if target.exists() and mode == 'merge':
                    skipped_auth += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(payload_data, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                restored += 1
            except Exception as e:
                errors.append(f'auth {relative_name}: {e}')
        if restored:
            imported.append(f'{restored} auth_entries')
        if skipped_auth:
            skipped.append(f'{skipped_auth} auth_entries (already exist)')

    # --- base_config ---
    base_config = data.get('base_config')
    if isinstance(base_config, str) and base_config.strip():
        try:
            if not BASE_CONFIG.exists() or mode == 'replace':
                BASE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
                BASE_CONFIG.write_text(base_config, encoding='utf-8')
                imported.append('base_config')
            else:
                skipped.append('base_config (already exists)')
        except Exception as e:
            errors.append(f'base_config: {e}')

    # --- runtime_config (active config) ---
    runtime_config = data.get('runtime_config')
    if isinstance(runtime_config, str) and runtime_config.strip():
        try:
            if not RUNTIME_CONFIG.exists() or mode == 'replace':
                RUNTIME_CONFIG.parent.mkdir(parents=True, exist_ok=True)
                RUNTIME_CONFIG.write_text(runtime_config, encoding='utf-8')
                imported.append('runtime_config')
            else:
                skipped.append('runtime_config (already exists)')
        except Exception as e:
            errors.append(f'runtime_config: {e}')

    # --- sources_config ---
    sources_config = data.get('sources_config')
    if isinstance(sources_config, dict):
        try:
            if not SOURCES_CONFIG_FILE.exists() or mode == 'replace':
                SOURCES_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                SOURCES_CONFIG_FILE.write_text(
                    json.dumps(sources_config, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                imported.append('sources_config')
            else:
                skipped.append('sources_config (already exists)')
        except Exception as e:
            errors.append(f'sources_config: {e}')

    # --- model configs ---
    for key, filename in [
        ('model_overrides', 'provider_model_overrides.json'),
        ('aggregate_aliases', 'aggregate_model_aliases.json'),
        ('model_proxy_settings', 'model_proxy_settings.json'),
        ('model_thinking_configs', 'model_thinking_configs.json'),
    ]:
        model_data = data.get(key)
        if isinstance(model_data, (dict, list)):
            try:
                target = MODELS_DIR / filename
                if not target.exists() or mode == 'replace':
                    MODELS_DIR.mkdir(parents=True, exist_ok=True)
                    target.write_text(
                        json.dumps(model_data, ensure_ascii=False, indent=2),
                        encoding='utf-8',
                    )
                    imported.append(key)
                else:
                    skipped.append(f'{key} (already exists)')
            except Exception as e:
                errors.append(f'{key}: {e}')

    # Build summary message
    parts = [f'Imported {len(imported)} items.']
    if skipped:
        parts.append(f'Skipped {len(skipped)} existing items.')
    if errors:
        parts.append(f'{len(errors)} errors.')
    message = ' '.join(parts)

    return {
        'ok': len(errors) == 0,
        'imported': imported,
        'skipped': skipped,
        'errors': errors,
        'message': message,
    }


def _clear_importable_data():
    """Clear all data that can be re-imported (used in replace mode)."""
    # Clear state
    if STATE_FILE.exists():
        try:
            STATE_FILE.write_text('{}', encoding='utf-8')
        except Exception:
            pass

    # Clear API keys
    if API_KEYS_FILE.exists():
        try:
            _save_keys([])
        except Exception:
            pass

    # Clear API key usage
    if API_KEYS_USAGE_FILE.exists():
        try:
            API_KEYS_USAGE_FILE.write_text('{}', encoding='utf-8')
        except Exception:
            pass

    # Clear auth provider directories
    for sub in AUTH_DIR.iterdir():
        if sub.is_dir() and sub.name.lower() not in ('archive', 'backups', 'logs'):
            try:
                shutil.rmtree(sub)
            except Exception:
                pass
    # Clear root-level auth JSON files (legacy)
    for f in AUTH_DIR.glob('*.json'):
        try:
            f.unlink()
        except Exception:
            pass

    # Clear runtime config
    if RUNTIME_CONFIG.exists():
        try:
            RUNTIME_CONFIG.unlink()
        except Exception:
            pass

    # Clear model configs
    for filename in [
        'provider_model_overrides.json',
        'aggregate_model_aliases.json',
        'model_proxy_settings.json',
        'model_thinking_configs.json',
    ]:
        target = MODELS_DIR / filename
        if target.exists():
            try:
                target.unlink()
            except Exception:
                pass

    # Clear base config
    if BASE_CONFIG.exists():
        try:
            BASE_CONFIG.unlink()
        except Exception:
            pass
