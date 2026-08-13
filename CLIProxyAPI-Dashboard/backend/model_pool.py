"""Dashboard-managed model pool references and runtime expansion."""

import json
import logging
import re
import shutil
from pathlib import Path
from backend.paths import MODEL_POOLS_FILE, MODEL_POOLS_AUTH_DIR

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 2


def _safe_folder_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', str(name or '').strip()) or 'unnamed_pool'


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def _load_model_pool_index() -> list[dict]:
    data = _read_json(MODEL_POOLS_FILE, {})
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get('pools'), list):
        return data['pools']
    return []


def _node_ref(node: dict, index: int) -> str:
    return str(node.get('node_ref') or node.get('id') or f'node-{index + 1}').strip()


def _normalize_pool(pool: dict) -> dict:
    pool = dict(pool or {})
    call_id = str(pool.get('call_id') or pool.get('pool_ref') or pool.get('id') or '').strip()
    pool_ref = str(pool.get('pool_ref') or call_id or pool.get('id') or '').strip()
    nodes = []
    for index, raw in enumerate(pool.get('nodes') or []):
        if not isinstance(raw, dict):
            continue
        node = dict(raw)
        node['node_ref'] = _node_ref(node, index)
        node['id'] = node['node_ref']
        node['enabled'] = bool(node.get('enabled', True))
        node['weight'] = max(1, int(node.get('weight') or 1))
        nodes.append(node)

    presets = []
    for index, raw in enumerate(pool.get('presets') or []):
        if not isinstance(raw, dict):
            continue
        preset = dict(raw)
        preset_id = str(preset.get('preset_id') or preset.get('id') or preset.get('call_id') or call_id).strip()
        preset['preset_id'] = preset_id
        preset['call_id'] = str(preset.get('call_id') or preset_id).strip()
        preset['enabled'] = bool(preset.get('enabled', True))
        refs = []
        for ref_index, raw_ref in enumerate(preset.get('node_refs') or []):
            if isinstance(raw_ref, str):
                raw_ref = {'node_ref': raw_ref}
            if not isinstance(raw_ref, dict):
                continue
            ref = dict(raw_ref)
            ref['node_ref'] = str(ref.get('node_ref') or ref.get('id') or '').strip()
            if not ref['node_ref']:
                continue
            ref['weight'] = max(1, int(ref.get('weight') or 1))
            ref['enabled'] = bool(ref.get('enabled', True))
            refs.append(ref)
        preset['node_refs'] = refs
        presets.append(preset)

    if not presets and nodes:
        preset_id = str(nodes[0].get('upstream_id') or call_id).strip() or call_id
        presets = [{
            'preset_id': preset_id,
            'call_id': call_id or preset_id,
            'enabled': bool(pool.get('enabled', True)),
            'node_refs': [
                {'node_ref': node['node_ref'], 'weight': node.get('weight', 1), 'enabled': node.get('enabled', True),
                 'upstream_id': node.get('upstream_id', '')}
                for node in nodes
            ],
        }]

    pool['id'] = str(pool.get('id') or pool_ref or f'pool-{call_id}').strip()
    pool['pool_ref'] = pool_ref or pool['id']
    pool['call_id'] = call_id or pool['pool_ref']
    pool['provider'] = str(pool.get('provider') or f'pool-{pool["call_id"]}').strip().lower()
    pool['enabled'] = bool(pool.get('enabled', True))
    pool['nodes'] = nodes
    pool['presets'] = presets
    return pool


def load_model_pools() -> list[dict]:
    """Load panel pools and migrate legacy auth files on first read."""
    indexed = [_normalize_pool(p) for p in _load_model_pool_index() if isinstance(p, dict)]
    legacy = _load_legacy_model_pools()
    if not legacy:
        return indexed

    merged = list(indexed)
    by_key = {
        str(pool.get('call_id') or pool.get('pool_ref') or pool.get('id') or '').strip().lower(): index
        for index, pool in enumerate(merged)
    }
    changed = False
    for legacy_pool in legacy:
        key = str(legacy_pool.get('call_id') or legacy_pool.get('pool_ref') or legacy_pool.get('id') or '').strip().lower()
        existing_index = by_key.get(key)
        if existing_index is None:
            by_key[key] = len(merged)
            merged.append(legacy_pool)
            changed = True
            continue
        existing = merged[existing_index]
        if legacy_pool.get('nodes'):
            existing['nodes'] = legacy_pool['nodes']
            existing['presets'] = legacy_pool.get('presets') or existing.get('presets', [])
            changed = True

    if changed or legacy:
        # Persist the normalized index and reference manifests immediately so
        # old root-level base_config/node files cannot remain authoritative.
        save_model_pools(merged)
    return merged


def _load_legacy_model_pools() -> list[dict]:
    if not MODEL_POOLS_AUTH_DIR.is_dir():
        return []
    dirs = []
    if list(MODEL_POOLS_AUTH_DIR.glob('node_*.json')) or (MODEL_POOLS_AUTH_DIR / 'base_config.json').exists():
        dirs.append(MODEL_POOLS_AUTH_DIR)
    dirs.extend(sorted(p for p in MODEL_POOLS_AUTH_DIR.iterdir() if p.is_dir()))
    pools = []
    for pool_dir in dirs:
        base = _read_json(pool_dir / 'base_config.json', {}) or {}
        nodes = []
        for path in sorted(pool_dir.glob('node_*.json')):
            data = _read_json(path, {}) or {}
            content = data.get('content') if isinstance(data.get('content'), dict) else data
            metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else data
            nodes.append({
                'id': str(metadata.get('node_id') or data.get('id') or path.stem),
                'base_url': str(content.get('base_url') or '').strip(),
                'api_key': str(content.get('api_key') or '').strip(),
                'upstream_id': str(content.get('model') or data.get('upstream_id') or '').strip(),
                'weight': int(metadata.get('weight') or data.get('weight') or 1),
                'proxy_url': str(metadata.get('proxy_url') or data.get('proxy_url') or '').strip(),
                'enabled': not bool(data.get('disabled')) and bool(data.get('enabled', True)),
            })
        pools.append(_normalize_pool({
            'id': base.get('id') or f'pool-{pool_dir.name}',
            'provider': base.get('provider'),
            'call_id': base.get('call_id') or pool_dir.name,
            'enabled': base.get('enabled', True),
            'nodes': nodes,
        }))
    return pools


def _write_reference_manifests(pools: list[dict]) -> None:
    MODEL_POOLS_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    valid = set()
    for pool in pools:
        folder = _safe_folder_name(pool['pool_ref'])
        valid.add(folder)
        pool_dir = MODEL_POOLS_AUTH_DIR / folder
        pool_dir.mkdir(parents=True, exist_ok=True)
        for old in pool_dir.glob('*.json'):
            old.unlink()
        for index, preset in enumerate(pool.get('presets') or []):
            aliases = [str(preset.get('call_id') or preset['preset_id']).strip()]
            if pool['call_id'] not in aliases:
                aliases.append(pool['call_id'])
            manifest = {
                'metadata': {
                    'file_schema': 'cliproxyapi-model-pool-ref-v2',
                    'source': 'model_pool',
                    'pool_ref': pool['pool_ref'],
                    'preset_id': preset['preset_id'],
                    'aliases': aliases,
                    'enabled': bool(pool['enabled'] and preset.get('enabled', True)),
                },
                'references': {
                    'node_refs': [
                        {key: value for key, value in ref.items() if key in ('node_ref', 'weight', 'enabled', 'upstream_id')}
                        for ref in preset.get('node_refs', [])
                    ]
                }
            }
            (pool_dir / f'preset_{index + 1}.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    for child in MODEL_POOLS_AUTH_DIR.iterdir():
        if child.is_dir() and child.name not in valid:
            shutil.rmtree(child, ignore_errors=True)
        elif child.is_file() and (child.name == 'base_config.json' or child.name.startswith('node_')):
            child.unlink(missing_ok=True)


def save_model_pools(pools: list[dict]) -> bool:
    try:
        normalized = [_normalize_pool(p) for p in pools if isinstance(p, dict)]
        MODEL_POOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        MODEL_POOLS_FILE.write_text(json.dumps({'schema_version': SCHEMA_VERSION, 'pools': normalized}, ensure_ascii=False, indent=2), encoding='utf-8')
        _write_reference_manifests(normalized)
        return True
    except Exception as err:
        logger.error('Failed to save model pools: %s', err)
        return False


def remap_local_pool_proxy_urls(proxy_url: str) -> dict:
    """Persistently update local egress overrides stored on pool nodes."""
    try:
        from backend.local_proxy import remap_local_proxy_url
    except Exception as exc:
        return {'ok': False, 'changed_nodes': 0, 'error': str(exc)}

    pools = load_model_pools()
    changed_nodes = 0
    normalized = []
    for raw_pool in pools:
        pool = _normalize_pool(raw_pool)
        for node in pool.get('nodes') or []:
            previous = str(node.get('proxy_url') or '').strip()
            updated = remap_local_proxy_url(previous, proxy_url)
            if updated != previous:
                node['proxy_url'] = updated
                changed_nodes += 1
        normalized.append(pool)

    if changed_nodes and not save_model_pools(normalized):
        return {'ok': False, 'changed_nodes': 0, 'error': 'Failed to save model pool settings.'}
    return {'ok': True, 'changed_nodes': changed_nodes}


def resolve_model_pool_references(pools: list[dict] | None = None) -> tuple[list[dict], list[str]]:
    resolved, warnings = [], []
    pools = pools if pools is not None else load_model_pools()
    aliases = {}
    for raw_pool in pools:
        pool = _normalize_pool(raw_pool)
        if not pool['enabled']:
            continue
        node_map = {str(node.get('node_ref') or node.get('id')): node for node in pool.get('nodes', [])}
        for preset in pool.get('presets', []):
            if not preset.get('enabled', True):
                continue
            preset_id = str(preset.get('preset_id') or '').strip()
            preset_alias = str(preset.get('call_id') or preset_id).strip()
            alias_list = []
            for alias in (preset_id, preset_alias, pool['call_id']):
                if alias and alias not in alias_list:
                    alias_list.append(alias)
            route_nodes = []
            for ref in preset.get('node_refs', []):
                if not ref.get('enabled', True):
                    continue
                node = node_map.get(str(ref.get('node_ref') or '').strip())
                if not node:
                    warnings.append(f'{pool["pool_ref"]}/{preset_id}: missing node {ref.get("node_ref")}')
                    continue
                upstream = str(ref.get('upstream_id') or node.get('upstream_id') or preset_id or pool['call_id']).strip()
                if not node.get('base_url') or not node.get('api_key') or not upstream:
                    warnings.append(f'{pool["pool_ref"]}/{preset_id}: node {ref.get("node_ref")} is incomplete')
                    continue
                route_nodes.append({
                    'provider': pool['provider'], 'base_url': str(node['base_url']).rstrip('/'),
                    'api_key': node['api_key'], 'proxy_url': node.get('proxy_url', ''),
                    'weight': max(1, int(ref.get('weight') or node.get('weight') or 1)),
                    'models': [upstream], 'aliases': alias_list,
                })
            if not route_nodes:
                continue
            route_key = (pool['pool_ref'], preset_id)
            for alias in alias_list:
                alias_key = alias.lower()
                prior = aliases.get(alias_key)
                if prior and prior != route_key:
                    warnings.append(f'alias conflict: {alias}')
                    continue
                aliases[alias_key] = route_key
            resolved.extend(route_nodes)
    return resolved, warnings


def get_model_pool_manual_entries() -> list[dict]:
    entries, _warnings = resolve_model_pool_references()
    result = []
    for entry in entries:
        aliases = entry.pop('aliases', [])
        for alias in aliases:
            item = dict(entry)
            item['direct_alias'] = alias
            item['mappings'] = [{'call_id': alias, 'upstream_id': entry['models'][0], 'provider': entry['provider']}]
            result.append(item)
    return result
