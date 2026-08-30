import ipaddress
import json
import re
from collections import Counter, defaultdict

from backend.auth import list_auth_files, get_configured_aggregate_models
from backend.request_metrics.merge import _provider_lookup
from backend.paths import STORAGE_DIR

_HISTORICAL_PROVIDER = '历史残留'
_MODEL_SLUG_RE = re.compile(r'[^a-z0-9]+')


def _slug_model_id(value: str) -> str:
    text = _MODEL_SLUG_RE.sub('-', str(value or '').strip().lower()).strip('-')
    return text


def _override_model_lookup() -> tuple[dict[str, str], dict[str, dict], set[str]]:
    """Scan mapping overrides (including deleted) for historical provider attribution."""
    by_call_id: dict[str, str] = {}
    by_upstream: dict[str, dict] = {}
    providers: set[str] = set()
    try:
        from backend.auth import _load_model_mapping_overrides
        overrides = _load_model_mapping_overrides()
    except Exception:
        return by_call_id, by_upstream, providers

    for provider, model_map in (overrides or {}).items():
        provider_key = str(provider or '').strip().lower()
        if not provider_key or not isinstance(model_map, dict):
            continue
        providers.add(provider_key)
        for upstream_id, entry in model_map.items():
            upstream = str(upstream_id or '').strip()
            mappings = entry.get('mappings') if isinstance(entry, dict) else []
            if not isinstance(mappings, list):
                continue
            for item in mappings:
                if not isinstance(item, dict):
                    continue
                call_id = str(item.get('call_id') or '').strip()
                target_provider = str(item.get('provider') or provider_key).strip().lower() or provider_key
                target_upstream = str(item.get('upstream_id') or upstream).strip()
                deleted = bool(item.get('deleted'))
                row = {
                    'source_provider': provider_key,
                    'target_provider': target_provider,
                    'upstream_id': target_upstream,
                    'lookup_upstream_id': upstream or target_upstream,
                    'call_id': call_id or target_upstream,
                    'deleted': deleted,
                }
                providers.add(target_provider)
                if call_id:
                    by_call_id.setdefault(call_id, target_provider)
                    by_upstream.setdefault(call_id, row)
                for key in (target_upstream, upstream):
                    if key:
                        by_upstream.setdefault(key, row)
                # Historical probes often used provider-slug call ids.
                for raw in (call_id, target_upstream, upstream):
                    slug = _slug_model_id(raw)
                    if not slug:
                        continue
                    synthetic = f'{provider_key}-{slug}'
                    by_call_id.setdefault(synthetic, target_provider)
                    by_upstream.setdefault(synthetic, row)
    return by_call_id, by_upstream, providers


def _guess_provider_from_model_id(model_id: str, known_providers: set[str] | None = None) -> str:
    value = str(model_id or '').strip().lower()
    if not value or value in {'unknown', '-', '未识别'}:
        return ''
    providers = {str(item or '').strip().lower() for item in (known_providers or set()) if str(item or '').strip()}
    # Prefer longer prefixes so "openrouter" wins over "open".
    for provider in sorted(providers, key=len, reverse=True):
        if value == provider or value.startswith(f'{provider}-') or value.startswith(f'{provider}/'):
            return provider
    return ''


def resolve_model_stats_provider(model_id: str, provider_models: list[dict] | None = None) -> dict:
    """Resolve provider metadata for a stats model id, including historical overrides."""
    model_value = str(model_id or '').strip()
    if not model_value:
        return {
            'provider': _HISTORICAL_PROVIDER,
            'delete_provider': '',
            'delete_upstream_id': '',
            'actual_model': '',
            'can_delete': False,
            'is_historical': True,
            'source': 'unknown',
        }

    by_call_id, by_upstream = _provider_lookup(provider_models or [])
    ov_call, ov_up, ov_providers = _override_model_lookup()
    known_providers = set(by_call_id.values()) | set(ov_providers)
    for item in provider_models or []:
        for key in ('provider', 'lookup_provider'):
            value = str(item.get(key) or '').strip().lower()
            if value:
                known_providers.add(value)

    row = by_upstream.get(model_value) or ov_up.get(model_value)
    provider = str(by_call_id.get(model_value) or ov_call.get(model_value) or '').strip().lower()
    if not provider and row:
        provider = str(row.get('target_provider') or row.get('source_provider') or '').strip().lower()
    if not provider:
        provider = _guess_provider_from_model_id(model_value, known_providers)

    deleted = bool((row or {}).get('deleted')) if row else False
    active = bool(by_call_id.get(model_value) or (row and not deleted and model_value in by_upstream))
    delete_provider = str((row or {}).get('source_provider') or provider or '').strip().lower()
    delete_upstream_id = str(
        (row or {}).get('lookup_upstream_id')
        or (row or {}).get('upstream_id')
        or ''
    ).strip()
    actual_model = delete_upstream_id
    is_historical = (not active) or deleted or provider in {'', '-', 'unknown'}
    if not provider:
        provider = _HISTORICAL_PROVIDER
        is_historical = True
    if provider == 'unknown':
        provider = _HISTORICAL_PROVIDER
        is_historical = True

    return {
        'provider': provider,
        'delete_provider': delete_provider if delete_provider not in {'', 'unknown', _HISTORICAL_PROVIDER} else '',
        'delete_upstream_id': delete_upstream_id,
        'actual_model': actual_model,
        'can_delete': bool(delete_provider and delete_upstream_id and delete_provider not in {'unknown', _HISTORICAL_PROVIDER}),
        'is_historical': is_historical,
        'source': 'active' if active and not deleted else 'historical',
    }


def merge_cumulative_model_test_stats(
    rows: list[dict],
    cum_by_model: dict | None,
    provider_models: list[dict] | None = None,
) -> list[dict]:
    """Overlay cumulative tokens and append historical-only models with provider attribution."""
    result = [dict(row) for row in (rows or [])]
    cum_by_model = cum_by_model or {}
    for row in result:
        model_id = str(row.get('model') or '').strip()
        cum = cum_by_model.get(model_id) if model_id else None
        if isinstance(cum, dict):
            row['prompt_tokens'] = int(cum.get('prompt_tokens') or 0)
            row['completion_tokens'] = int(cum.get('completion_tokens') or 0)
            row['total_tokens'] = int(cum.get('total_tokens') or 0)
            row['cumulative_request_count'] = int(cum.get('request_count') or 0)
        meta = resolve_model_stats_provider(model_id, provider_models)
        provider = str(row.get('provider') or '').strip()
        if not provider or provider in {'-', 'unknown', '未识别'}:
            row['provider'] = meta['provider']
        if not row.get('delete_provider'):
            row['delete_provider'] = meta['delete_provider']
        if not row.get('delete_upstream_id'):
            row['delete_upstream_id'] = meta['delete_upstream_id']
        if not row.get('actual_model'):
            row['actual_model'] = meta['actual_model']
        if not row.get('can_delete'):
            row['can_delete'] = meta['can_delete']
        row['is_historical'] = bool(meta['is_historical']) if provider in {'', '-', 'unknown', '未识别', _HISTORICAL_PROVIDER} else False
        row.setdefault('source', meta['source'])

    seen_models = {str(row.get('model') or '').strip() for row in result if str(row.get('model') or '').strip()}
    for model_id, cum in cum_by_model.items():
        model_value = str(model_id or '').strip()
        if not model_value or model_value in seen_models:
            continue
        if not isinstance(cum, dict) or not cum.get('request_count'):
            continue
        meta = resolve_model_stats_provider(model_value, provider_models)
        result.append({
            'model': model_value,
            'provider': meta['provider'],
            'delete_provider': meta['delete_provider'],
            'delete_upstream_id': meta['delete_upstream_id'],
            'actual_model': meta['actual_model'],
            'can_delete': meta['can_delete'],
            'is_historical': bool(meta['is_historical']),
            'source': 'cumulative-only' if meta['is_historical'] else 'active-cumulative',
            'total_tests': 0,
            'success_count': 0,
            'failure_count': 0,
            'success_rate': 0,
            'success_rate_percent': 0,
            'last_log_at': 0,
            'last_log_success': None,
            'last_log_status_code': None,
            'last_error_summary': '',
            'available': None,
            'tested_at': 0,
            'test_status_code': None,
            'test_message': '',
            'working_path': '',
            'failure_kind': '',
            'prompt_tokens': int(cum.get('prompt_tokens') or 0),
            'completion_tokens': int(cum.get('completion_tokens') or 0),
            'total_tokens': int(cum.get('total_tokens') or 0),
            'cumulative_request_count': int(cum.get('request_count') or 0),
        })
    return result


def _safe_int(value, default=0) -> int:
    """安全地将值转为 int，失败时返回 default。防止非数字字符串导致 ValueError。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _proxy_style_mask(key: str) -> str:
    """与代理日志中一致的掩码格式：前 4 位 + ... + 后 4 位。"""
    key = str(key or '')
    if len(key) <= 8:
        return key
    return key[:4] + '...' + key[-4:]


def _get_default_api_key_masked() -> str:
    """从 runtime/state.json 读取代理当前使用的默认 API Key，并转成日志掩码格式。"""
    try:
        state_path = STORAGE_DIR / 'runtime' / 'state.json'
        if state_path.exists():
            data = json.loads(state_path.read_text(encoding='utf-8', errors='ignore'))
            key = str(data.get('last_proxy_api_key') or '').strip()
            if key:
                return _proxy_style_mask(key)
    except Exception:
        pass
    return _proxy_style_mask('cliproxyapi')


def _build_api_key_label_map() -> dict[str, dict[str, str]]:
    """构建 proxy-style masked_key → {label, name} 的映射表，用于客户端命名。

    日志里 Authorization 头的掩码格式是代理生成的（前4+...+后4），
    与 backend.api_keys._mask_key 不同，所以要单独计算。
    """
    try:
        from backend.api_keys import _load_keys
        mapping: dict[str, dict[str, str]] = {}
        data = _load_keys()
        keys = data if isinstance(data, list) else data.get('keys', [])
        for entry in keys:
            full_key = str(entry.get('key') or '').strip()
            name = str(entry.get('name') or '').strip()
            note = str(entry.get('note') or '').strip()
            if not full_key:
                continue
            masked = _proxy_style_mask(full_key)
            label = name or note or masked
            mapping[masked] = {'label': label, 'name': name, 'note': note}
        return mapping
    except Exception:
        return {}

def _client_ip_type(ip: str) -> str:
    value = str(ip or '').strip()
    if not value or value == 'unknown':
        return 'unknown'
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return 'unknown'
    if getattr(parsed, 'ipv4_mapped', None):
        parsed = parsed.ipv4_mapped
    if parsed.is_loopback:
        return 'loopback'
    if parsed.is_private:
        return 'private'
    return 'public'


def _client_status(success_rate: float, count_5xx: int, count_4xx: int) -> str:
    if count_5xx > 0 or success_rate < 0.8:
        return 'warning'
    if count_4xx > 0 or success_rate < 0.95:
        return 'notice'
    return 'healthy'


def summarize_clients(events: list[dict], cumulative_stats: dict | None = None) -> list[dict]:
    """按 API Key 分组聚合客户端统计。无 Key 时归入默认 API Key。

    可选传入 cumulative_stats，把历史累积中有但最近窗口里没有的 Key 也补进来，
    并把请求数和 Token 消耗替换为全量累积值（状态/成功率/延迟仍基于最近窗口）。
    """
    default_key = _get_default_api_key_masked()
    groups = defaultdict(list)
    for event in events or []:
        key = str(event.get('api_key_masked') or '').strip()
        if not key:
            # 旧日志/归档事件没有 api_key_masked，统一归入默认 Key
            key = default_key
        groups[key].append(event)

    label_map = _build_api_key_label_map()
    cum_by_client = (cumulative_stats or {}).get('by_client') or {}

    def _resolve_label(group_key: str) -> str:
        # 优先用虚拟 API Key 系统的名称
        info = label_map.get(group_key)
        if info:
            return info.get('label') or group_key
        return group_key

    rows = []
    seen_keys = set()
    for group_key, items in groups.items():
        seen_keys.add(group_key)
        total = len(items)
        success = sum(1 for item in items if item.get('success'))
        latencies = [int(item.get('latency_ms')) for item in items if isinstance(item.get('latency_ms'), int)]
        model_counter = Counter(str(item.get('requested_model') or '').strip() for item in items if str(item.get('requested_model') or '').strip())
        path_counter = Counter(str(item.get('path') or '').strip() for item in items if str(item.get('path') or '').strip())
        success_rate = round((success / total) if total else 0, 4)
        count_4xx = sum(1 for item in items if 400 <= _safe_int(item.get('status_code')) < 500)
        count_5xx = sum(1 for item in items if _safe_int(item.get('status_code')) >= 500)

        # 收集所有涉及的 IP（保留作为辅助信息）
        ips = list(dict.fromkeys(str(item.get('client_ip') or '').strip() for item in items if str(item.get('client_ip') or '').strip()))
        ip_types = list(dict.fromkeys(_client_ip_type(ip) for ip in ips))

        label = _resolve_label(group_key)

        # 用累积统计覆盖请求数和 Token（全量），最近窗口只保留状态/成功率/延迟等
        cum = cum_by_client.get(group_key)
        if cum:
            total_requests = int(cum.get('request_count') or 0)
            prompt_tokens = int(cum.get('prompt_tokens') or 0)
            completion_tokens = int(cum.get('completion_tokens') or 0)
            total_tokens = int(cum.get('total_tokens') or 0)
        else:
            total_requests = total
            prompt_tokens = sum(_safe_int(item.get('prompt_tokens')) for item in items)
            completion_tokens = sum(_safe_int(item.get('completion_tokens')) for item in items)
            total_tokens = sum(_safe_int(item.get('total_tokens')) for item in items)

        rows.append({
            'key': group_key,
            'label': label,
            'is_api_key': bool(any(str(item.get('api_key_masked') or '').strip() for item in items)),
            'ips': ips,
            'ip_types': ip_types,
            'ip_type': ip_types[0] if ip_types else 'unknown',
            'total_requests': total_requests,
            'last_seen': max(_safe_int(item.get('timestamp')) for item in items),
            'success_rate': success_rate,
            'failure_count': total - success,
            'error_rate': round(((total - success) / total) if total else 0, 4),
            'count_4xx': count_4xx,
            'count_5xx': count_5xx,
            'status': _client_status(success_rate, count_5xx, count_4xx),
            'top_model': model_counter.most_common(1)[0][0] if model_counter else '',
            'top_path': path_counter.most_common(1)[0][0] if path_counter else '',
            'avg_latency_ms': int(sum(latencies) / len(latencies)) if latencies else None,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens,
        })

    # 合并累积统计中的客户端（补全最近窗口里没有的 Key）
    for client_key, cum in cum_by_client.items():
        if client_key in seen_keys:
            continue
        if not cum.get('request_count'):
            continue
        seen_keys.add(client_key)
        label = _resolve_label(client_key)
        rows.append({
            'key': client_key,
            'label': label,
            'is_api_key': client_key != default_key,
            'ips': [],
            'ip_types': [],
            'ip_type': 'apikey',
            'total_requests': int(cum.get('request_count') or 0),
            'last_seen': 0,
            'success_rate': 0,
            'failure_count': 0,
            'error_rate': 0,
            'count_4xx': 0,
            'count_5xx': 0,
            'status': 'unknown',
            'top_model': '',
            'top_path': '',
            'avg_latency_ms': None,
            'prompt_tokens': int(cum.get('prompt_tokens') or 0),
            'completion_tokens': int(cum.get('completion_tokens') or 0),
            'total_tokens': int(cum.get('total_tokens') or 0),
        })

    # 把所有已配置的虚拟 API Key 都展示出来（没有请求显示为 0）
    for client_key in label_map:
        if client_key in seen_keys:
            continue
        seen_keys.add(client_key)
        rows.append({
            'key': client_key,
            'label': _resolve_label(client_key),
            'is_api_key': client_key != default_key,
            'ips': [],
            'ip_types': [],
            'ip_type': 'apikey',
            'total_requests': 0,
            'last_seen': 0,
            'success_rate': 0,
            'failure_count': 0,
            'error_rate': 0,
            'count_4xx': 0,
            'count_5xx': 0,
            'status': 'unknown',
            'top_model': '',
            'top_path': '',
            'avg_latency_ms': None,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total_tokens': 0,
        })

    rows.sort(key=lambda item: (-int(item.get('total_requests') or 0), -int(item.get('last_seen') or 0)))
    return rows


def summarize_models(events: list[dict], provider_models: list[dict], runtime_test_state: dict, runtime_model_ids: list[str] | None = None) -> list[dict]:
    runtime_model_ids = runtime_model_ids or []
    runtime_set = {str(item or '').strip() for item in runtime_model_ids if str(item or '').strip()}
    test_results = runtime_test_state.get('results') if isinstance(runtime_test_state, dict) else {}
    call_counter = Counter(str(item.get('requested_model') or '').strip() for item in events or [] if str(item.get('requested_model') or '').strip())

    rows = []
    
    # 1. Add provider models
    for provider_item in provider_models or []:
        provider = str(provider_item.get('provider') or '').strip().lower()
        for row in provider_item.get('rows') or []:
            call_id = str(row.get('call_id') or '').strip()
            if not call_id:
                continue
            test_state = test_results.get(call_id) if isinstance(test_results, dict) else {}
            if not isinstance(test_state, dict):
                test_state = {}
            rows.append({
                'provider': provider,
                'call_id': call_id,
                'upstream_id': str(row.get('upstream_id') or '').strip(),
                'capability_score': int(row.get('capability_score') or 0),
                'runtime_registered': call_id in runtime_set,
                'request_count': int(call_counter.get(call_id, 0)),
                'available': bool(test_state.get('available')) if isinstance(test_state, dict) else None,
                'failure_kind': str(test_state.get('failure_kind') or '').strip(),
                'status_code': test_state.get('status_code') if isinstance(test_state, dict) else None,
                'message': str(test_state.get('message') or '').strip() if isinstance(test_state, dict) else '',
                'tested_at': int(test_state.get('tested_at') or 0) if isinstance(test_state, dict) else 0,
            })
            
    # 2. Add aggregate models
    try:
        aggregates = get_configured_aggregate_models()
        for agg in aggregates:
            call_id = str(agg.get('alias_id') or '').strip()
            if not call_id:
                continue
            test_state = test_results.get(call_id) if isinstance(test_results, dict) else {}
            if not isinstance(test_state, dict):
                test_state = {}
            rows.append({
                'provider': 'aggregate',
                'call_id': call_id,
                'upstream_id': f"({len(agg.get('members', []))} models)",
                'capability_score': 0,
                'runtime_registered': call_id in runtime_set,
                'request_count': int(call_counter.get(call_id, 0)),
                'available': bool(test_state.get('available')) if isinstance(test_state, dict) else None,
                'failure_kind': str(test_state.get('failure_kind') or '').strip(),
                'status_code': test_state.get('status_code') if isinstance(test_state, dict) else None,
                'message': str(test_state.get('message') or '').strip() if isinstance(test_state, dict) else '',
                'tested_at': int(test_state.get('tested_at') or 0) if isinstance(test_state, dict) else 0,
            })
    except Exception:
        pass

    rows.sort(key=lambda item: (-int(item.get('request_count') or 0), -int(item.get('capability_score') or 0), item.get('call_id') or ''))
    return rows


def summarize_model_test_stats(events: list[dict], provider_models: list[dict], runtime_test_state: dict, limit: int = 500) -> list[dict]:
    by_call_id, by_upstream = _provider_lookup(provider_models or [])
    test_results = runtime_test_state.get('results') if isinstance(runtime_test_state, dict) else {}
    test_counts = runtime_test_state.get('test_counts') if isinstance(runtime_test_state, dict) else {}
    try:
        aggregate_map = {
            str(item.get('alias_id') or '').strip(): item
            for item in get_configured_aggregate_models()
            if str(item.get('alias_id') or '').strip()
        }
    except Exception:
        aggregate_map = {}
    grouped = defaultdict(list)

    for event in (events or [])[:max(1, int(limit or 500))]:
        model_id = str(event.get('requested_model') or '').strip()
        if not model_id:
            continue
        grouped[model_id].append(event)

    known_models = set(grouped.keys())
    if isinstance(test_results, dict):
        known_models.update(str(model_id or '').strip() for model_id in test_results.keys() if str(model_id or '').strip())

    # Add all configured aggregate IDs so they appear in stats even if not yet called/tested
    for call_id, provider in by_call_id.items():
        if provider == 'aggregate':
            known_models.add(call_id)

    rows = []
    for model_id in known_models:
        items = grouped.get(model_id) or []
        total = len(items)
        success_count = sum(1 for item in items if item.get('success'))
        failure_count = total - success_count
        last_event = max(items, key=lambda item: _safe_int(item.get('timestamp')), default={})
        test_state = test_results.get(model_id) if isinstance(test_results, dict) else {}
        if not isinstance(test_state, dict):
            test_state = {}
        lookup_row = by_upstream.get(model_id)
        provider = str(by_call_id.get(model_id) or '').strip().lower()
        aggregate_item = aggregate_map.get(model_id) if provider == 'aggregate' else None
        upstream_row = lookup_row if not provider else None
        if upstream_row:
            provider = str(upstream_row.get('target_provider') or upstream_row.get('source_provider') or '').strip().lower()
        if not provider:
            provider = str(last_event.get('inferred_provider') or '').strip().lower()
        resolved_meta = resolve_model_stats_provider(model_id, provider_models)
        if not provider or provider in {'unknown', '-'}:
            provider = str(resolved_meta.get('provider') or _HISTORICAL_PROVIDER)
        is_historical = bool(resolved_meta.get('is_historical')) or provider == _HISTORICAL_PROVIDER
        delete_provider = str(
            (lookup_row or {}).get('source_provider')
            or resolved_meta.get('delete_provider')
            or provider
            or ''
        ).strip().lower()
        if delete_provider in {'unknown', _HISTORICAL_PROVIDER, '-'}:
            delete_provider = str(resolved_meta.get('delete_provider') or '').strip().lower()
        delete_upstream_id = str(
            (lookup_row or {}).get('lookup_upstream_id')
            or (lookup_row or {}).get('upstream_id')
            or resolved_meta.get('delete_upstream_id')
            or ''
        ).strip()
        actual_model = delete_upstream_id or str(resolved_meta.get('actual_model') or '')
        aggregate_members = aggregate_item.get('members') if isinstance(aggregate_item, dict) else []
        if aggregate_members:
            member_labels = []
            for member in aggregate_members:
                if not isinstance(member, dict):
                    continue
                member_provider = str(member.get('target_provider') or member.get('provider') or '').strip().lower()
                member_upstream = str(member.get('runtime_upstream_id') or member.get('upstream_id') or member.get('call_id') or '').strip()
                if member_provider and member_upstream:
                    member_labels.append(f'{member_provider}:{member_upstream}')
                elif member_upstream:
                    member_labels.append(member_upstream)
            if member_labels:
                actual_model = ', '.join(member_labels[:3])
                if len(member_labels) > 3:
                    actual_model += f' +{len(member_labels) - 3}'

        available = None
        tested_at = 0
        test_status_code = None
        test_message = ''
        working_path = ''
        failure_kind = ''
        manual_test_success = None
        manual_tests_total = 0
        manual_success_count = 0
        manual_failure_count = 0
        count_state = test_counts.get(model_id) if isinstance(test_counts, dict) else {}
        if isinstance(count_state, dict):
            manual_tests_total = max(0, int(count_state.get('total') or 0))
            manual_success_count = max(0, int(count_state.get('success') or 0))
            manual_failure_count = max(0, int(count_state.get('failure') or 0))
            if manual_tests_total < manual_success_count + manual_failure_count:
                manual_tests_total = manual_success_count + manual_failure_count
        if isinstance(test_state, dict) and test_state:
            available = bool(test_state.get('available'))
            tested_at = int(test_state.get('tested_at') or 0)
            test_status_code = test_state.get('status_code')
            test_message = str(test_state.get('message') or '').strip()
            working_path = str(test_state.get('working_path') or '').strip()
            failure_kind = str(test_state.get('failure_kind') or '').strip()
            status = str(test_state.get('status') or '').strip().lower()
            if status != 'testing' and manual_tests_total <= 0:
                manual_tests_total = 1
                manual_test_success = bool(available)
        elif aggregate_members:
            member_results = []
            for member in aggregate_members:
                if not isinstance(member, dict):
                    continue
                member_call_id = str(member.get('call_id') or '').strip()
                member_result = test_results.get(member_call_id) if isinstance(test_results, dict) else None
                if isinstance(member_result, dict) and member_result:
                    member_results.append(member_result)
            if member_results:
                available = any(bool(result.get('available')) for result in member_results)
                newest = max(member_results, key=lambda result: int(result.get('tested_at') or 0), default={})
                tested_at = int(newest.get('tested_at') or 0)
                test_status_code = newest.get('status_code')
                test_message = str(newest.get('message') or '').strip()
                working_path = str(newest.get('working_path') or '').strip()
                failure_kind = '' if available else str(newest.get('failure_kind') or '').strip()

        final_total = total + manual_tests_total
        if manual_tests_total > 0 and (manual_success_count or manual_failure_count):
            final_success_count = success_count + manual_success_count
            final_failure_count = failure_count + manual_failure_count
        else:
            final_success_count = success_count + (1 if manual_test_success is True else 0)
            final_failure_count = final_total - final_success_count

        prompt_tokens = sum(_safe_int(item.get('prompt_tokens')) for item in items)
        completion_tokens = sum(_safe_int(item.get('completion_tokens')) for item in items)
        total_tokens = sum(_safe_int(item.get('total_tokens')) for item in items)
        rows.append({
            'model': model_id,
            'provider': provider,
            'delete_provider': delete_provider,
            'delete_upstream_id': delete_upstream_id,
            'actual_model': actual_model,
            'can_delete': bool(
                delete_provider
                and delete_upstream_id
                and delete_provider not in {'unknown', _HISTORICAL_PROVIDER, '-'}
            ),
            'is_historical': is_historical,
            'source': 'historical' if is_historical else 'active',
            'total_tests': final_total,
            'success_count': final_success_count,
            'failure_count': final_failure_count,
            'success_rate': round((final_success_count / final_total) if final_total else 0, 4),
            'success_rate_percent': round(((final_success_count / final_total) * 100) if final_total else 0, 2),
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens,
            'last_log_at': _safe_int(last_event.get('timestamp')),
            'last_log_success': bool(last_event.get('success')) if last_event else None,
            'last_log_status_code': last_event.get('status_code') if last_event else None,
            'last_error_summary': str(last_event.get('error_summary') or '').strip() if last_event else '',
            'available': available,
            'tested_at': tested_at,
            'test_status_code': test_status_code,
            'test_message': test_message,
            'working_path': working_path,
            'failure_kind': failure_kind,
        })

    rows.sort(key=lambda item: (
        -int(item.get('total_tests') or 0),
        -int(item.get('tested_at') or 0),
        str(item.get('model') or ''),
    ))
    return rows


def summarize_auth_health(auth_items: list[dict], events: list[dict], provider_models: list[dict], runtime_test_state: dict) -> list[dict]:
    auth_items = auth_items or list_auth_files()
    by_call_id, _ = _provider_lookup(provider_models)
    test_results = runtime_test_state.get('results') if isinstance(runtime_test_state, dict) else {}
    provider_stats = defaultdict(lambda: {'last_failure': 0, 'reason': '', 'requests': 0, 'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0})

    for event in events or []:
        model_id = str(event.get('requested_model') or '').strip()
        provider = str(event.get('inferred_provider') or by_call_id.get(model_id) or '').strip().lower()
        if not provider:
            continue
        provider_stats[provider]['requests'] += 1
        provider_stats[provider]['prompt_tokens'] += _safe_int(event.get('prompt_tokens'))
        provider_stats[provider]['completion_tokens'] += _safe_int(event.get('completion_tokens'))
        provider_stats[provider]['total_tokens'] += _safe_int(event.get('total_tokens'))
        if not event.get('success'):
            ts = _safe_int(event.get('timestamp'))
            if ts >= provider_stats[provider]['last_failure']:
                provider_stats[provider]['last_failure'] = ts
                provider_stats[provider]['reason'] = str(event.get('error_summary') or '').strip()

    rows = []
    for item in auth_items:
        provider = str(item.get('provider') or '').strip().lower()
        matching_results = [
            result for call_id, result in (test_results.items() if isinstance(test_results, dict) else [])
            if str(by_call_id.get(call_id) or '').strip().lower() == provider and isinstance(result, dict)
        ]
        available_count = sum(1 for result in matching_results if result.get('available'))
        failure_count = sum(1 for result in matching_results if result and not result.get('available'))
        state = 'unknown'
        if available_count and failure_count:
            state = 'degraded'
        elif available_count:
            state = 'healthy'
        elif failure_count:
            state = 'failed'
        rows.append({
            'auth_id': str(item.get('id') or '').strip(),
            'name': str(item.get('name') or '').strip(),
            'provider': provider,
            'email': str(item.get('email') or '').strip(),
            'label': str(item.get('email') or item.get('name') or '').strip(),
            'state': state,
            'recent_failure_reason': provider_stats[provider]['reason'],
            'recent_failure_at': int(provider_stats[provider]['last_failure'] or 0),
            'request_count': int(provider_stats[provider]['requests'] or 0),
            'prompt_tokens': int(provider_stats[provider]['prompt_tokens'] or 0),
            'completion_tokens': int(provider_stats[provider]['completion_tokens'] or 0),
            'total_tokens': int(provider_stats[provider]['total_tokens'] or 0),
            'available_models': available_count,
            'failed_models': failure_count,
        })
    rows.sort(key=lambda item: (item.get('state') != 'healthy', -int(item.get('request_count') or 0), item.get('name') or ''))
    return rows
