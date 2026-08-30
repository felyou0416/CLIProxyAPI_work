"""Cross-environment dashboard data export / import.

Supports:
- Dev monorepo (CLIProxyAPI/storage next to source)
- Packaged desktop or portable install (CLIPROXYAPI_STORAGE_DIR)

Export is path-agnostic where possible. On import, absolute paths inside YAML
configs (auth-dir, etc.) are rewritten to the target machine's storage layout.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from backend.api_keys import API_KEYS_FILE, API_KEYS_USAGE_FILE, _load_keys, _save_keys
from backend.auth import _read_auth_payload, list_auth_files
from backend.paths import (
    AUTH_DIR,
    BASE_CONFIG,
    MODELS_DIR,
    RUNTIME_CONFIG,
    RUNTIME_VARIANT,
    SOURCES_CONFIG_FILE,
    STATE_FILE,
    STORAGE_DIR,
)
from backend.state import load_state, save_state

EXPORT_VERSION = 3
SUPPORTED_IMPORT_VERSIONS = {1, 2, 3}

# Keys that must never be blindly overwritten from another machine.
_STATE_LOCAL_ONLY_KEYS = frozenset(
    {
        # process runtime / machine-local
        'proxy_pid',
        'proxy_port',
        'dashboard_pid',
        'last_proxy_start',
        'last_proxy_stop',
    }
)

_MODEL_FILES = (
    ('model_overrides', 'provider_model_overrides.json'),
    ('aggregate_aliases', 'aggregate_model_aliases.json'),
    ('model_proxy_settings', 'model_proxy_settings.json'),
    ('model_thinking_configs', 'model_thinking_configs.json'),
)

_ABS_PATH_KEYS = (
    'auth-dir',
    'auth_dir',
    'config-dir',
    'config_dir',
    'log-dir',
    'log_dir',
    'logging-dir',
)


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


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def detect_environment() -> dict:
    """Describe current install profile for export metadata / UI."""
    storage_env = (
        os.environ.get('CLIPROXYAPI_STORAGE_DIR', '').strip()
        or os.environ.get('RELAYX_STORAGE_DIR', '').strip()
    )
    dashboard_root_env = os.environ.get('RELAYX_DASHBOARD_ROOT', '').strip()
    frozen = bool(getattr(sys, 'frozen', False))
    # Packaged desktop or installed binary: storage is injected via env or frozen.
    if storage_env or dashboard_root_env or frozen:
        profile = 'user'
    else:
        profile = 'dev'
    return {
        'profile': profile,  # dev | user
        'runtime_variant': RUNTIME_VARIANT,
        'frozen': frozen,
        'storage_dir': str(STORAGE_DIR),
        'auth_dir': str(AUTH_DIR),
        'has_storage_env': bool(storage_env),
        'has_dashboard_root_env': bool(dashboard_root_env),
        'platform': sys.platform,
    }


def _collect_auth_entries() -> list[dict]:
    """Collect auth entries with relative paths for portable restore."""
    items = []
    seen = set()
    for auth_file in list_auth_files():
        source = auth_file.get('path')
        if not source or not Path(source).exists():
            continue
        source_path = Path(source)
        relative = auth_file.get('relativeName') or source_path.name
        # Normalize separators for cross-platform import
        relative = str(relative).replace('\\', '/').lstrip('/')
        dedup_key = relative.lower()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        try:
            payload = _read_auth_payload(source_path)
        except Exception:
            payload = None
        items.append(
            {
                'id': auth_file.get('id'),
                'name': auth_file.get('name') or source_path.name,
                'provider': auth_file.get('provider'),
                'relative_name': relative,
                'payload': payload,
            }
        )
    return items


def _summarize_data(data: dict) -> dict:
    auth_n = len(data.get('auth_entries') or []) if isinstance(data.get('auth_entries'), list) else 0
    keys_n = len(data.get('api_keys') or []) if isinstance(data.get('api_keys'), list) else 0
    return {
        'auth_entries': auth_n,
        'api_keys': keys_n,
        'has_state': isinstance(data.get('state'), dict),
        'has_base_config': bool(str(data.get('base_config') or '').strip()),
        'has_runtime_config': bool(str(data.get('runtime_config') or '').strip()),
        'has_sources_config': isinstance(data.get('sources_config'), dict),
        'has_model_overrides': data.get('model_overrides') is not None,
        'has_aggregate_aliases': data.get('aggregate_aliases') is not None,
        'has_model_proxy_settings': data.get('model_proxy_settings') is not None,
        'has_model_thinking_configs': data.get('model_thinking_configs') is not None,
    }


def export_all() -> dict:
    state = load_state()
    api_keys = _load_keys()
    env = detect_environment()
    data = {
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
    }
    return {
        'ok': True,
        'version': EXPORT_VERSION,
        'exported_at': datetime.now().isoformat(timespec='seconds'),
        'environment': env,
        'summary': _summarize_data(data),
        'data': data,
    }


def _extract_data_blob(payload: dict) -> dict:
    """Accept v1 (flat), v2/v3 (under data)."""
    if not isinstance(payload, dict):
        return {}
    nested = payload.get('data')
    if isinstance(nested, dict) and (
        'state' in nested
        or 'api_keys' in nested
        or 'auth_entries' in nested
        or 'runtime_config' in nested
        or 'base_config' in nested
    ):
        return nested
    # v1 flat layout
    return payload


def _normalize_version(payload: dict) -> int | None:
    raw = payload.get('version')
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _rewrite_yaml_paths(text: str) -> tuple[str, list[str]]:
    """Rewrite machine-local absolute paths in YAML config text for this install."""
    if not text or not text.strip():
        return text, []
    notes: list[str] = []
    out = text
    # auth-dir / similar: force local AUTH_DIR (forward slashes for YAML portability)
    local_auth = str(AUTH_DIR).replace('\\', '/')
    for key in _ABS_PATH_KEYS:
        pattern = re.compile(
            rf'^(\s*{re.escape(key)}\s*:\s*)(["\']?)([^"\'\n#]+)\2(\s*(?:#.*)?)?$',
            re.MULTILINE | re.IGNORECASE,
        )

        def _sub(match, _key=key, _local=local_auth):
            raw = (match.group(3) or '').strip()
            if not raw:
                return match.group(0)
            # Only rewrite absolute / drive-letter / UNC-looking paths
            is_abs = (
                raw.startswith('/')
                or raw.startswith('\\')
                or re.match(r'^[A-Za-z]:[\\/]', raw) is not None
            )
            if not is_abs and 'auth' not in _key.lower():
                return match.group(0)
            if raw.replace('\\', '/') == _local:
                return match.group(0)
            notes.append(f'{_key}: {raw} -> {_local}')
            quote = match.group(2) or '"'
            tail = match.group(4) or ''
            return f'{match.group(1)}{quote}{_local}{quote}{tail}'

        out = pattern.sub(_sub, out)

    # If export came from another machine and still embeds old storage roots in free text,
    # leave them unless they match known keys — safer than global replace.
    return out, notes


def _merge_json_blob(existing, incoming, *, mode: str):
    if mode == 'replace' or existing is None:
        return incoming
    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = dict(existing)
        merged.update(incoming)
        return merged
    if isinstance(existing, list) and isinstance(incoming, list):
        # Prefer keep-existing for lists without stable ids
        return existing if existing else incoming
    return existing if existing not in (None, {}, []) else incoming


def _merge_state(current: dict, incoming: dict, *, mode: str) -> dict:
    if mode == 'replace':
        base = {}
    else:
        base = dict(current or {})
    for key, value in (incoming or {}).items():
        if key in _STATE_LOCAL_ONLY_KEYS:
            continue
        base[key] = value
    return base


def import_all(payload: dict, *, mode: str = 'merge') -> dict:
    if not isinstance(payload, dict):
        return {'ok': False, 'message': 'Invalid import data format.'}

    version = _normalize_version(payload)
    if version is None:
        return {'ok': False, 'message': 'Missing version in import data.'}
    if version not in SUPPORTED_IMPORT_VERSIONS:
        return {
            'ok': False,
            'message': (
                f'Unsupported export version {version}. '
                f'Supported: {sorted(SUPPORTED_IMPORT_VERSIONS)}'
            ),
        }

    data = _extract_data_blob(payload)
    if not isinstance(data, dict) or not data:
        return {'ok': False, 'message': 'Import file has no usable data section.'}

    source_env = payload.get('environment') if isinstance(payload.get('environment'), dict) else {}
    target_env = detect_environment()
    path_rewrites: list[str] = []

    imported: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []

    if source_env.get('profile') and source_env.get('profile') != target_env.get('profile'):
        warnings.append(
            f"cross-profile import: source={source_env.get('profile')} → target={target_env.get('profile')}"
        )

    if mode == 'replace':
        _clear_importable_data()
        imported.append('cleared existing data')

    # --- state ---
    state = data.get('state')
    if isinstance(state, dict):
        try:
            current = load_state() if mode == 'merge' else {}
            merged = _merge_state(current, state, mode=mode)
            save_state(merged)
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
                added = 0
                for key in api_keys:
                    if not isinstance(key, dict):
                        continue
                    kid = str(key.get('id') or '')
                    kval = str(key.get('key') or '')
                    if kid and kid in existing_ids:
                        continue
                    if kval and kval in existing_keys:
                        continue
                    existing.append(key)
                    added += 1
                _save_keys(existing)
                if added == 0 and api_keys:
                    skipped.append(f'{len(api_keys)} api_keys (already exist)')
            imported.append(f'{len(api_keys)} api_keys')
        except Exception as e:
            errors.append(f'api_keys: {e}')

    # --- auth_entries ---
    auth_entries = data.get('auth_entries')
    if isinstance(auth_entries, list):
        restored = 0
        skipped_auth = 0
        for entry in auth_entries:
            if not isinstance(entry, dict):
                continue
            payload_data = entry.get('payload')
            relative_name = (
                entry.get('relative_name')
                or entry.get('filename')
                or entry.get('name')
                or ''
            )
            relative_name = str(relative_name).replace('\\', '/').lstrip('/')
            # Block path traversal
            if not payload_data or not relative_name or '..' in relative_name.split('/'):
                continue
            try:
                target = AUTH_DIR / relative_name
                # Ensure still under AUTH_DIR
                target.resolve().relative_to(AUTH_DIR.resolve())
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
            rewritten, notes = _rewrite_yaml_paths(base_config)
            path_rewrites.extend(f'base_config {n}' for n in notes)
            if not BASE_CONFIG.exists() or mode == 'replace':
                _write_text(BASE_CONFIG, rewritten)
                imported.append('base_config')
            else:
                skipped.append('base_config (already exists)')
        except Exception as e:
            errors.append(f'base_config: {e}')

    # --- runtime_config (active config) ---
    runtime_config = data.get('runtime_config')
    if isinstance(runtime_config, str) and runtime_config.strip():
        try:
            rewritten, notes = _rewrite_yaml_paths(runtime_config)
            path_rewrites.extend(f'runtime_config {n}' for n in notes)
            if not RUNTIME_CONFIG.exists() or mode == 'replace':
                _write_text(RUNTIME_CONFIG, rewritten)
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
                _write_json(SOURCES_CONFIG_FILE, sources_config)
                imported.append('sources_config')
            else:
                # merge shallow keys
                existing = _read_json_file(SOURCES_CONFIG_FILE) or {}
                if isinstance(existing, dict):
                    merged = dict(existing)
                    for k, v in sources_config.items():
                        if k not in merged or mode == 'replace':
                            merged[k] = v
                    _write_json(SOURCES_CONFIG_FILE, merged)
                    imported.append('sources_config (merged)')
                else:
                    skipped.append('sources_config (already exists)')
        except Exception as e:
            errors.append(f'sources_config: {e}')

    # --- model configs ---
    for key, filename in _MODEL_FILES:
        model_data = data.get(key)
        if isinstance(model_data, (dict, list)):
            try:
                target = MODELS_DIR / filename
                if not target.exists() or mode == 'replace':
                    _write_json(target, model_data)
                    imported.append(key)
                else:
                    existing = _read_json_file(target)
                    merged = _merge_json_blob(existing, model_data, mode=mode)
                    _write_json(target, merged)
                    imported.append(f'{key} (merged)')
            except Exception as e:
                errors.append(f'{key}: {e}')

    if path_rewrites:
        warnings.extend(path_rewrites[:20])
        if len(path_rewrites) > 20:
            warnings.append(f'… +{len(path_rewrites) - 20} more path rewrites')

    parts = [f'Imported {len(imported)} items.']
    if skipped:
        parts.append(f'Skipped {len(skipped)} existing items.')
    if warnings:
        parts.append(f'{len(warnings)} notes.')
    if errors:
        parts.append(f'{len(errors)} errors.')
    message = ' '.join(parts)

    return {
        'ok': len(errors) == 0,
        'imported': imported,
        'skipped': skipped,
        'errors': errors,
        'warnings': warnings,
        'message': message,
        'source_environment': source_env or None,
        'target_environment': target_env,
        'restart_recommended': bool(
            any(
                x.startswith('runtime_config')
                or x.startswith('base_config')
                or 'auth_entries' in x
                or x.startswith('model_')
                or x.startswith('aggregate_')
                for x in imported
            )
        ),
    }


def _clear_importable_data():
    """Clear data that can be re-imported (replace mode)."""
    if STATE_FILE.exists():
        try:
            STATE_FILE.write_text('{}', encoding='utf-8')
        except Exception:
            pass

    if API_KEYS_FILE.exists():
        try:
            _save_keys([])
        except Exception:
            pass

    if API_KEYS_USAGE_FILE.exists():
        try:
            API_KEYS_USAGE_FILE.write_text('{}', encoding='utf-8')
        except Exception:
            pass

    if AUTH_DIR.exists():
        for sub in AUTH_DIR.iterdir():
            if sub.is_dir() and sub.name.lower() not in ('archive', 'backups', 'logs'):
                try:
                    shutil.rmtree(sub)
                except Exception:
                    pass
        for f in AUTH_DIR.glob('*.json'):
            try:
                f.unlink()
            except Exception:
                pass

    if RUNTIME_CONFIG.exists():
        try:
            RUNTIME_CONFIG.unlink()
        except Exception:
            pass

    for _, filename in _MODEL_FILES:
        target = MODELS_DIR / filename
        if target.exists():
            try:
                target.unlink()
            except Exception:
                pass

    if BASE_CONFIG.exists():
        try:
            BASE_CONFIG.unlink()
        except Exception:
            pass
