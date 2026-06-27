import ipaddress
from collections import Counter, defaultdict

from backend.auth import list_auth_files, get_configured_aggregate_models
from backend.request_metrics.merge import _provider_lookup

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


def summarize_clients(events: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for event in events or []:
        ip = str(event.get('client_ip') or '').strip() or 'unknown'
        groups[ip].append(event)

    rows = []
    for ip, items in groups.items():
        total = len(items)
        success = sum(1 for item in items if item.get('success'))
        latencies = [int(item.get('latency_ms')) for item in items if isinstance(item.get('latency_ms'), int)]
        model_counter = Counter(str(item.get('requested_model') or '').strip() for item in items if str(item.get('requested_model') or '').strip())
        path_counter = Counter(str(item.get('path') or '').strip() for item in items if str(item.get('path') or '').strip())
        success_rate = round((success / total) if total else 0, 4)
        count_4xx = sum(1 for item in items if 400 <= int(item.get('status_code') or 0) < 500)
        count_5xx = sum(1 for item in items if int(item.get('status_code') or 0) >= 500)
        rows.append({
            'ip': ip,
            'ip_type': _client_ip_type(ip),
            'total_requests': total,
            'last_seen': max(int(item.get('timestamp') or 0) for item in items),
            'success_rate': success_rate,
            'failure_count': total - success,
            'error_rate': round(((total - success) / total) if total else 0, 4),
            'count_4xx': count_4xx,
            'count_5xx': count_5xx,
            'status': _client_status(success_rate, count_5xx, count_4xx),
            'top_model': model_counter.most_common(1)[0][0] if model_counter else '',
            'top_path': path_counter.most_common(1)[0][0] if path_counter else '',
            'avg_latency_ms': int(sum(latencies) / len(latencies)) if latencies else None,
            'prompt_tokens': sum(int(item.get('prompt_tokens') or 0) for item in items),
            'completion_tokens': sum(int(item.get('completion_tokens') or 0) for item in items),
            'total_tokens': sum(int(item.get('total_tokens') or 0) for item in items),
            'client_ip_source': next((str(item.get('client_ip_source') or '').strip() for item in items if str(item.get('client_ip_source') or '').strip()), ''),
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
        last_event = max(items, key=lambda item: int(item.get('timestamp') or 0), default={})
        test_state = test_results.get(model_id) if isinstance(test_results, dict) else {}
        lookup_row = by_upstream.get(model_id)
        provider = str(by_call_id.get(model_id) or '').strip().lower()
        aggregate_item = aggregate_map.get(model_id) if provider == 'aggregate' else None
        upstream_row = lookup_row if not provider else None
        if upstream_row:
            provider = str(upstream_row.get('target_provider') or upstream_row.get('source_provider') or '').strip().lower()
        if not provider:
            provider = str(last_event.get('inferred_provider') or '').strip().lower()
        if not provider:
            continue
        delete_provider = str((lookup_row or {}).get('source_provider') or provider or '').strip().lower()
        delete_upstream_id = str(
            (lookup_row or {}).get('lookup_upstream_id')
            or (lookup_row or {}).get('upstream_id')
            or ''
        ).strip()
        actual_model = delete_upstream_id
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

        rows.append({
            'model': model_id,
            'provider': provider,
            'delete_provider': delete_provider,
            'delete_upstream_id': delete_upstream_id,
            'actual_model': actual_model,
            'can_delete': bool(delete_provider and delete_upstream_id),
            'total_tests': final_total,
            'success_count': final_success_count,
            'failure_count': final_failure_count,
            'success_rate': round((final_success_count / final_total) if final_total else 0, 4),
            'success_rate_percent': round(((final_success_count / final_total) * 100) if final_total else 0, 2),
            'last_log_at': int(last_event.get('timestamp') or 0),
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
        provider_stats[provider]['prompt_tokens'] += int(event.get('prompt_tokens') or 0)
        provider_stats[provider]['completion_tokens'] += int(event.get('completion_tokens') or 0)
        provider_stats[provider]['total_tokens'] += int(event.get('total_tokens') or 0)
        if not event.get('success'):
            ts = int(event.get('timestamp') or 0)
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
        if available_count:
            state = 'healthy'
        elif failure_count:
            state = 'degraded'
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
