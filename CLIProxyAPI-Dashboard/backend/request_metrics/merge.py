from backend.auth import get_configured_aggregate_models
from backend.request_metrics.parsing import get_auth_id_index_snapshot


def _provider_lookup(provider_models: list[dict]) -> tuple[dict[str, str], dict[str, dict]]:
    by_call_id = {}
    by_upstream = {}
    for provider_item in provider_models or []:
        provider = str(provider_item.get('provider') or '').strip().lower()
        for row in provider_item.get('rows') or []:
            call_id = str(row.get('call_id') or '').strip()
            upstream_id = str(row.get('upstream_id') or '').strip()
            if call_id and provider and call_id not in by_call_id:
                by_call_id[call_id] = provider
            if call_id:
                by_upstream.setdefault(call_id, row)
            if upstream_id:
                by_upstream.setdefault(upstream_id, row)

    try:
        aggregates = get_configured_aggregate_models()
        for agg in aggregates:
            alias_id = str(agg.get('alias_id') or '').strip()
            members = agg.get('members') or []
            if alias_id and members and alias_id not in by_call_id:
                by_call_id[alias_id] = 'aggregate'
                by_upstream[alias_id] = {
                    'target_provider': 'aggregate',
                    'source_provider': 'aggregate',
                    'upstream_id': alias_id,
                    'lookup_upstream_id': alias_id,
                    'call_id': alias_id,
                }
    except Exception:
        pass

    return by_call_id, by_upstream


_EXTRA_MERGE_FIELDS = (
    'request_time',
    'upstream_request_time',
    'upstream_response_time',
    'response_time',
    'client_ip_source',
    'user_agent',
    'session_id',
    'upstream_latency_ms',
    'overhead_ms',
    'tps',
    'cached_tokens',
    'reasoning_tokens',
    'reasoning_effort',
    'auth_label',
    'auth_id',
    'auth_file',
    'auth_type',
    'upstream_url',
    'upstream_method',
    'stream',
    'trace_id',
    'upstream_request_id',
    'finish_reason',
    'prompt_preview',
    'response_preview',
    'log_file',
)


def _merge_route_fields(target: dict, source: dict) -> None:
    for field in ('actual_provider', 'actual_model', 'inferred_provider', 'routed_model', 'route_source', 'route_note'):
        if not str(target.get(field) or '').strip() and str(source.get(field) or '').strip():
            target[field] = str(source.get(field) or '').strip()
    if target.get('route_confidence') is None and source.get('route_confidence') is not None:
        target['route_confidence'] = source.get('route_confidence')


def _set_route_metadata(event: dict, source: str, confidence: float, note: str) -> None:
    if not isinstance(event, dict):
        return
    if source and not str(event.get('route_source') or '').strip():
        event['route_source'] = source
    if confidence is not None and event.get('route_confidence') is None:
        event['route_confidence'] = max(0.0, min(1.0, float(confidence)))
    if note and not str(event.get('route_note') or '').strip():
        event['route_note'] = note


def _resolve_route_fields(event: dict, by_call_id: dict[str, str], by_upstream: dict[str, dict]) -> None:
    actual_provider = str(event.get('actual_provider') or event.get('inferred_provider') or '').strip().lower()
    actual_model = str(event.get('actual_model') or event.get('routed_model') or '').strip()
    if actual_provider or actual_model:
        event['inferred_provider'] = actual_provider
        event['routed_model'] = actual_model
        if actual_provider:
            event['actual_provider'] = actual_provider
        if actual_model:
            event['actual_model'] = actual_model
        _set_route_metadata(event, 'precise-log', 1.0, 'captured from request log')
        return

    model_id = str(event.get('requested_model') or '').strip()
    inferred = ''
    routed = ''
    route_source = ''
    route_note = ''
    route_confidence = 0.0
    if model_id:
        row = by_upstream.get(model_id)
        if row:
            inferred = str(row.get('target_provider') or row.get('source_provider') or '').strip().lower()
            routed = str(row.get('upstream_id') or row.get('lookup_upstream_id') or '').strip()
            route_source = 'aggregate-config' if str(by_call_id.get(model_id) or '').strip().lower() == 'aggregate' else 'runtime-model-map'
            route_note = 'matched configured aggregate alias' if route_source == 'aggregate-config' else 'matched configured provider model'
            route_confidence = 0.55 if route_source == 'aggregate-config' else 0.8
        if not row:
            inferred = str(by_call_id.get(model_id) or '').strip()
            if inferred:
                route_source = 'registry-model-map'
                route_note = 'matched runtime registry entry'
                route_confidence = 0.45
    event['inferred_provider'] = inferred
    event['routed_model'] = routed
    _set_route_metadata(event, route_source or 'unknown', route_confidence, route_note or 'no precise upstream log available')


def merge_request_events(proxy_events: list[dict], precise_events: list[dict], error_events: list[dict], provider_models: list[dict] | None = None) -> list[dict]:
    provider_models = provider_models or []
    by_call_id, by_upstream = _provider_lookup(provider_models)

    precise_by_request_id = {}
    for event in precise_events or []:
        request_id = str(event.get('request_id') or '').strip()
        if request_id and request_id not in precise_by_request_id:
            precise_by_request_id[request_id] = dict(event)

    error_by_request_id = {}
    for event in error_events or []:
        request_id = str(event.get('request_id') or '').strip()
        if request_id and request_id not in error_by_request_id:
            error_by_request_id[request_id] = dict(event)

    items = []
    seen_request_ids = set()

    for event in proxy_events or []:
        copy = dict(event)
        request_id = str(copy.get('request_id') or '').strip()
        matched_precise = precise_by_request_id.get(request_id) if request_id else None
        matched_error = error_by_request_id.get(request_id) if request_id else None
        for matched in (matched_precise, matched_error):
            if not matched:
                continue
            if not str(copy.get('requested_model') or '').strip() and str(matched.get('requested_model') or '').strip():
                copy['requested_model'] = str(matched.get('requested_model') or '').strip()
            if not str(copy.get('error_summary') or '').strip() and not bool(copy.get('success')) and str(matched.get('error_summary') or '').strip():
                copy['error_summary'] = str(matched.get('error_summary') or '').strip()
            if copy.get('prompt_tokens') is None and matched.get('prompt_tokens') is not None:
                copy['prompt_tokens'] = matched.get('prompt_tokens')
            if copy.get('completion_tokens') is None and matched.get('completion_tokens') is not None:
                copy['completion_tokens'] = matched.get('completion_tokens')
            if copy.get('total_tokens') is None and matched.get('total_tokens') is not None:
                copy['total_tokens'] = matched.get('total_tokens')
            if not str(copy.get('api_key_masked') or '').strip() and str(matched.get('api_key_masked') or '').strip():
                copy['api_key_masked'] = str(matched.get('api_key_masked') or '').strip()
            if matched.get('latency_ms') is not None:
                copy['latency_ms'] = matched.get('latency_ms')
            if matched.get('tps') is not None:
                copy['tps'] = matched.get('tps')
            for field in _EXTRA_MERGE_FIELDS:
                if (copy.get(field) is None or copy.get(field) == '' or copy.get(field) is False) and (matched.get(field) is not None and matched.get(field) != ''):
                    copy[field] = matched.get(field)
            _merge_route_fields(copy, matched)
            notes = list(copy.get('notes') or [])
            for note in matched.get('notes') or []:
                if note not in notes:
                    notes.append(note)
            copy['notes'] = notes
        if request_id and (matched_precise or matched_error):
            seen_request_ids.add(request_id)
        _resolve_route_fields(copy, by_call_id, by_upstream)
        if not str(copy.get('route_source') or '').strip():
            _set_route_metadata(copy, 'unknown', 0.0, 'no route source resolved')
        items.append(copy)

    for event in precise_events or []:
        request_id = str(event.get('request_id') or '').strip()
        if request_id and request_id in seen_request_ids:
            continue
        copy = dict(event)
        matched_error = error_by_request_id.get(request_id) if request_id else None
        if matched_error and not str(copy.get('error_summary') or '').strip():
            copy['error_summary'] = str(matched_error.get('error_summary') or '').strip()
            notes = list(copy.get('notes') or [])
            for note in matched_error.get('notes') or []:
                if note not in notes:
                    notes.append(note)
            copy['notes'] = notes
        if matched_error:
            for field in _EXTRA_MERGE_FIELDS:
                if (copy.get(field) is None or copy.get(field) == '' or copy.get(field) is False) and (matched_error.get(field) is not None and matched_error.get(field) != ''):
                    copy[field] = matched_error.get(field)
        _resolve_route_fields(copy, by_call_id, by_upstream)
        if not str(copy.get('route_source') or '').strip():
            _set_route_metadata(copy, 'unknown', 0.0, 'no route source resolved')
        items.append(copy)
        if request_id:
            seen_request_ids.add(request_id)

    for event in error_events or []:
        request_id = str(event.get('request_id') or '').strip()
        if request_id and request_id in seen_request_ids:
            continue
        copy = dict(event)
        _resolve_route_fields(copy, by_call_id, by_upstream)
        if not str(copy.get('route_source') or '').strip():
            _set_route_metadata(copy, 'unknown', 0.0, 'no route source resolved')
        items.append(copy)

    # 补全 auth_file：旧的归档 jsonl（在反查功能上线前写入）没有这个字段，
    # 这里用 auth_id 现算一次兜底，确保面板始终能显示具体账号文件路径。
    # 注意：只在这里取一次索引快照（内部有 mtime 缓存，不会重复扫盘），
    # 循环内部只做内存字典查找，避免给每条事件都触发一次 stat() 系统调用。
    need_backfill = any(not str(item.get('auth_file') or '').strip() and str(item.get('auth_id') or '').strip() for item in items)
    if need_backfill:
        auth_idx = get_auth_id_index_snapshot()
        for item in items:
            if not str(item.get('auth_file') or '').strip():
                auth_id = str(item.get('auth_id') or '').strip()
                if auth_id:
                    entry = auth_idx.get(auth_id)
                    if entry and entry.get('auth_file'):
                        item['auth_file'] = entry['auth_file']

    items.sort(key=lambda item: int(item.get('timestamp') or 0), reverse=True)
    return items
