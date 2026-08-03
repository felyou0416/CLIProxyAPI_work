"""Model Load Balancer Pool (独立 Provider 轮询池) backend module."""

import json
import logging
import re
import shutil
from pathlib import Path
from backend.paths import MODEL_POOLS_FILE, MODEL_POOLS_AUTH_DIR

logger = logging.getLogger(__name__)


def _safe_folder_name(name: str) -> str:
    """Sanitize string for folder name."""
    s = str(name or '').strip()
    s = re.sub(r'[\\/:*?"<>|]', '_', s)
    return s or 'unnamed_pool'


def _load_model_pool_index() -> list[dict]:
    if not MODEL_POOLS_FILE.exists() or not MODEL_POOLS_FILE.is_file():
        return []
    try:
        data = json.loads(MODEL_POOLS_FILE.read_text(encoding='utf-8'))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get('pools'), list):
            return data['pools']
    except Exception as err:
        logger.error("Failed to read model_pools.json: %s", err)
    return []


def _read_pool_auth_dir(pool_dir: Path) -> dict | None:
    base_config_path = pool_dir / 'base_config.json'
    try:
        base_config = json.loads(base_config_path.read_text(encoding='utf-8')) if base_config_path.exists() else {}
    except Exception as err:
        logger.error("Failed to read pool config %s: %s", base_config_path, err)
        base_config = {}

    node_files = sorted(pool_dir.glob('node_*.json'))
    if not base_config and not node_files:
        return None

    first_node = {}
    nodes = []
    fallback_call_id = str(base_config.get('call_id') or pool_dir.name).strip()
    for nfile in node_files:
        try:
            ndata = json.loads(nfile.read_text(encoding='utf-8'))
            content = ndata.get('content') if isinstance(ndata.get('content'), dict) else ndata
            metadata = ndata.get('metadata') if isinstance(ndata.get('metadata'), dict) else ndata
            if not isinstance(content, dict):
                continue
            node = {
                'id': str(metadata.get('node_id') or ndata.get('id') or nfile.stem),
                'base_url': str(content.get('base_url') or '').strip(),
                'api_key': str(content.get('api_key') or '').strip(),
                'upstream_id': str(content.get('model') or ndata.get('upstream_id') or fallback_call_id).strip() or fallback_call_id,
                'weight': int(metadata.get('weight') or ndata.get('weight') or 1),
                'proxy_url': str(metadata.get('proxy_url') or ndata.get('proxy_url') or '').strip(),
                'enabled': not bool(ndata.get('disabled')) and bool(ndata.get('enabled', True))
            }
            nodes.append(node)
            if not first_node:
                first_node = node
        except Exception as err:
            logger.error("Failed to read pool node %s: %s", nfile, err)

    call_id = str(base_config.get('call_id') or '').strip()
    if not call_id and first_node:
        try:
            payload = json.loads((pool_dir / 'node_1.json').read_text(encoding='utf-8'))
            metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
            call_id = str(metadata.get('call_id') or '').strip()
        except Exception:
            call_id = ''
    call_id = call_id or pool_dir.name
    provider = str(base_config.get('provider') or '').strip()
    if not provider and first_node:
        try:
            payload = json.loads((pool_dir / 'node_1.json').read_text(encoding='utf-8'))
            content = payload.get('content') if isinstance(payload.get('content'), dict) else payload
            provider = str(content.get('provider') or '').strip()
        except Exception:
            provider = ''

    return {
        'id': str(base_config.get('id') or f'pool-{call_id}').strip(),
        'provider': provider or f'pool-{call_id}',
        'call_id': call_id,
        'enabled': bool(base_config.get('enabled', True)),
        'nodes': nodes
    }


def _load_auth_model_pools() -> list[dict]:
    if not MODEL_POOLS_AUTH_DIR.exists() or not MODEL_POOLS_AUTH_DIR.is_dir():
        return []
    candidates = []
    if (MODEL_POOLS_AUTH_DIR / 'base_config.json').exists() or list(MODEL_POOLS_AUTH_DIR.glob('node_*.json')):
        candidates.append(MODEL_POOLS_AUTH_DIR)
    candidates.extend(sorted(d for d in MODEL_POOLS_AUTH_DIR.iterdir() if d.is_dir()))
    return [pool for pool in (_read_pool_auth_dir(path) for path in candidates) if pool]


def load_model_pools() -> list[dict]:
    """Load the index and overlay its nodes with the actual auth-directory payloads."""
    indexed = _load_model_pool_index()
    auth_pools = _load_auth_model_pools()
    if not indexed:
        return auth_pools

    by_key = {}
    for pool in auth_pools:
        by_key[str(pool.get('call_id') or pool.get('id') or '').strip().lower()] = pool

    result = []
    consumed = set()
    for pool in indexed:
        if not isinstance(pool, dict):
            continue
        key = str(pool.get('call_id') or pool.get('id') or '').strip().lower()
        auth_pool = by_key.get(key)
        merged = dict(pool)
        if auth_pool and auth_pool.get('nodes'):
            merged['provider'] = auth_pool.get('provider') or merged.get('provider')
            merged['nodes'] = auth_pool['nodes']
            consumed.add(key)
        result.append(merged)

    for pool in auth_pools:
        key = str(pool.get('call_id') or pool.get('id') or '').strip().lower()
        if key not in consumed and not any(str(item.get('call_id') or item.get('id') or '').strip().lower() == key for item in result):
            result.append(pool)
    return result


def save_model_pools(pools: list[dict]) -> bool:
    """
    Save model pools data to storage/auth/model_pools/<model_id>/ directory structure.
    Also syncs to model_pools.json for fast caching.
    """
    try:
        # Save JSON index cache
        MODEL_POOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        MODEL_POOLS_FILE.write_text(
            json.dumps({'pools': pools}, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

        # Save to storage/auth/model_pools/<model_id>/
        MODEL_POOLS_AUTH_DIR.mkdir(parents=True, exist_ok=True)

        valid_folder_names = set()
        for pool in pools:
            if not isinstance(pool, dict):
                continue

            call_id = str(pool.get('call_id') or '').strip()
            if not call_id:
                continue

            folder_name = _safe_folder_name(call_id)
            valid_folder_names.add(folder_name)
            pool_dir = MODEL_POOLS_AUTH_DIR / folder_name
            pool_dir.mkdir(parents=True, exist_ok=True)

            # Write standard provider node files; pool metadata remains in model_pools.json.
            for legacy_config in pool_dir.glob('base_config.json'):
                try:
                    legacy_config.unlink()
                except OSError:
                    pass

            # Write node_*.json files
            existing_nodes = list((pool.get('nodes') or []))
            # Clean up old node files
            for old_node in pool_dir.glob('node_*.json'):
                try:
                    old_node.unlink()
                except OSError:
                    pass

            for idx, node in enumerate(existing_nodes):
                if not isinstance(node, dict):
                    continue
                node_file = pool_dir / f'node_{idx + 1}.json'
                node_id = str(node.get('id') or f'node-{idx + 1}').strip()
                upstream_id = str(node.get('upstream_id') or call_id).strip() or call_id
                provider = str(pool.get('provider') or 'model_pools').strip().lower()
                node_enabled = bool(node.get('enabled', True))
                node_data = {
                    'metadata': {
                        'file_schema': 'cliproxyapi-auth-v1',
                        'source': 'model_pool',
                        'pool_id': str(pool.get('id') or f'pool-{call_id}').strip(),
                        'call_id': call_id,
                        'node_id': node_id,
                        'weight': max(1, int(node.get('weight') or 1)),
                        'proxy_url': str(node.get('proxy_url') or '').strip(),
                    },
                    'disabled': not node_enabled,
                    'content': {
                        'type': 'api_key',
                        'provider': provider,
                        'base_url': str(node.get('base_url') or '').strip(),
                        'api_key': str(node.get('api_key') or '').strip(),
                        'model': upstream_id,
                        'models': [upstream_id],
                    }
                }
                node_file.write_text(
                    json.dumps(node_data, ensure_ascii=False, indent=2),
                    encoding='utf-8'
                )

        # Remove stale pool directories and the pre-migration root-level files.
        if MODEL_POOLS_AUTH_DIR.exists():
            for legacy_file in (
                MODEL_POOLS_AUTH_DIR / 'base_config.json',
                *MODEL_POOLS_AUTH_DIR.glob('node_*.json'),
            ):
                try:
                    if legacy_file.is_file():
                        legacy_file.unlink()
                except OSError as err:
                    logger.error("Failed to remove legacy pool file %s: %s", legacy_file, err)
            for child in MODEL_POOLS_AUTH_DIR.iterdir():
                if child.is_dir() and child.name not in valid_folder_names:
                    try:
                        shutil.rmtree(child)
                    except OSError as err:
                        logger.error("Failed to remove stale pool dir %s: %s", child, err)

        return True
    except Exception as err:
        logger.error("Failed to save model pools into storage/auth: %s", err)
        return False


def get_model_pool_manual_entries() -> list[dict]:
    """
    Convert all enabled model pools into manual entry formats for openai-compatibility synthesis.
    Each enabled node becomes an entry with provider name, base_url, api_key, weight, proxy_url, and model mapping.
    """
    pools = load_model_pools()
    entries = []

    for pool in pools:
        if not isinstance(pool, dict) or not pool.get('enabled', True):
            continue

        provider_name = str(pool.get('provider') or '').strip().lower()
        call_id = str(pool.get('call_id') or '').strip()
        nodes = pool.get('nodes') or []

        if not provider_name or not call_id or not nodes:
            continue

        for idx, node in enumerate(nodes):
            if not isinstance(node, dict) or not node.get('enabled', True):
                continue

            base_url = str(node.get('base_url') or '').strip()
            api_key = str(node.get('api_key') or '').strip()
            upstream_id = str(node.get('upstream_id') or call_id).strip() or call_id
            weight = int(node.get('weight') or 1)
            proxy_url = str(node.get('proxy_url') or '').strip()

            if not base_url or not api_key:
                continue

            entry = {
                'provider': provider_name,
                'base_url': base_url,
                'api_key': api_key,
                'weight': max(1, weight),
                'proxy_url': proxy_url,
                'direct_alias': call_id,
                'models': [upstream_id],
                'mappings': [
                    {
                        'call_id': call_id,
                        'upstream_id': upstream_id,
                        'provider': provider_name,
                    }
                ]
            }
            entries.append(entry)

    return entries
