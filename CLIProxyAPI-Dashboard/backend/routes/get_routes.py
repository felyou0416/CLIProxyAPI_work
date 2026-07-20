from backend.paths import ROOT, GENERATED_IMAGES_DIR
from backend.api_keys import list_api_keys
from urllib.parse import parse_qs
from backend.auth import list_auth_files, get_configured_provider_models, get_model_route_preview, get_configured_aggregate_models, get_aggregate_route_health, get_manual_provider_presets, filter_provider_models_by_runtime, annotate_provider_models_runtime, canonicalize_auth_ref, get_model_proxy_settings, _current_route_strategy, derive_global_aggregate_aliases, _read_auth_payload
from backend.state import load_state, normalize_route_strategy, save_state
from backend.processes import current_status, firewall_access_status, custom_firewall_status, normalize_firewall_ports, normalize_firewall_protocols, port_binding_status, ip_helper_status, grok2api_port
from backend.security import generate_security_report
from backend.tools import get_tool_outputs, query_models, test_proxy, get_provider_model_test_state
from backend.model_thinking import load_model_thinking_configs, collect_thinking_candidates, collect_all_configured_models
from backend.terminals import list_terminals, read_terminal
from backend.request_metrics import parse_proxy_requests, parse_precise_request_events, parse_error_logs, merge_request_events, summarize_clients, summarize_models, summarize_model_test_stats, summarize_auth_health, ensure_observability_cache, refresh_observability_cache, get_cumulative_stats, merge_cumulative_model_test_stats
from backend.routes.helpers import send_json, send_file
from backend.system_proxy import get_system_proxy_status
import time
import mimetypes


def _image_test_candidates():
    candidates = {}

    def add_candidate(model_id, provider='', upstream_id='', source='provider'):
        model_value = str(model_id or '').strip()
        if not model_value:
            return
        item = candidates.setdefault(model_value, {
            'model': model_value,
            'provider': str(provider or '').strip() or '-',
            'upstream_id': str(upstream_id or '').strip(),
            'sources': [],
        })
        source_value = str(source or '').strip()
        if source_value and source_value not in item['sources']:
            item['sources'].append(source_value)
        if provider and item.get('provider') in ('', '-'):
            item['provider'] = str(provider).strip()
        if upstream_id and not item.get('upstream_id'):
            item['upstream_id'] = str(upstream_id).strip()

    provider_items = get_configured_provider_models(include_override_only=False)
    for item in provider_items:
        provider = str(item.get('lookup_provider') or item.get('provider') or '').strip().lower()
        for row in item.get('rows') or []:
            upstream_id = str(row.get('lookup_upstream_id') or row.get('upstream_id') or row.get('name') or '').strip()
            runtime_upstream_id = str(row.get('upstream_id') or row.get('name') or upstream_id).strip()
            call_id = str(row.get('call_id') or row.get('alias') or row.get('name') or '').strip()
            if 'image' in derive_global_aggregate_aliases(provider, upstream_id, runtime_upstream_id):
                add_candidate(call_id, provider, upstream_id or runtime_upstream_id, 'provider-image-rule')

    for aggregate in get_configured_aggregate_models():
        if str(aggregate.get('alias_id') or '').strip().lower() != 'image':
            continue
        for member in aggregate.get('members') or []:
            add_candidate(
                member.get('call_id') or member.get('runtime_upstream_id') or member.get('upstream_id'),
                member.get('provider') or member.get('target_provider'),
                member.get('upstream_id') or member.get('runtime_upstream_id'),
                'image-aggregate',
            )

    items = sorted(candidates.values(), key=lambda item: (
        str(item.get('provider') or ''),
        str(item.get('model') or ''),
    ))
    return {'ok': True, 'items': items}


def handle_get(handler, parsed):
    params = parse_qs(parsed.query)
    if parsed.path in ('/', '/index.html'):
        try:
            import re
            skeleton_path = ROOT / 'index.html'
            if skeleton_path.exists() and skeleton_path.is_file():
                text = skeleton_path.read_text(encoding='utf-8')
                
                # Match comments like <!-- INCLUDE: sections/overview.html -->
                pattern = r'<!--\s*INCLUDE:\s*(.*?)\s*-->'
                
                def replace_match(match):
                    rel_path = match.group(1).strip()
                    target_file = ROOT / rel_path
                    try:
                        # Ensure no directory traversal outside of root
                        target_file.resolve().relative_to(ROOT.resolve())
                    except ValueError:
                        return f"<!-- ERROR: Include path {rel_path} outside root -->"
                    
                    if target_file.exists() and target_file.is_file():
                        return target_file.read_text(encoding='utf-8')
                    return f"<!-- ERROR: Include file {rel_path} not found -->"
                
                compiled_text = re.sub(pattern, replace_match, text)
                try:
                    from backend.settings import get_version_info
                    version_info = get_version_info()
                    version = version_info.get('item', {}).get('version', '1.0.0')
                    compiled_text = re.sub(r'(\.js|\.css)\?v=[^\'\"\s>]+', f'\\1?v={version}', compiled_text)
                except Exception:
                    pass
                compiled = compiled_text.encode('utf-8')
                
                handler.send_response(200)
                handler.send_header('Content-Type', 'text/html; charset=utf-8')
                handler.send_header('Content-Length', str(len(compiled)))
                handler.end_headers()
                handler.wfile.write(compiled)
                return True
        except Exception as e:
            # Fall back to standard send_file if dynamic compiling fails
            pass
        send_file(handler, ROOT / 'index.html', root=ROOT)
        return True
    if parsed.path == '/dashboard.css':
        send_file(handler, ROOT / 'dashboard.css', 'text/css; charset=utf-8', root=ROOT)
        return True
    if parsed.path.startswith('/js/'):
        send_file(handler, ROOT / parsed.path.lstrip('/'), 'application/javascript; charset=utf-8', root=ROOT)
        return True
    if parsed.path.startswith('/css/'):
        send_file(handler, ROOT / parsed.path.lstrip('/'), 'text/css; charset=utf-8', root=ROOT)
        return True
    if parsed.path.startswith('/sections/'):
        send_file(handler, ROOT / parsed.path.lstrip('/'), 'text/html; charset=utf-8', root=ROOT)
        return True
    if parsed.path.startswith('/generated/images/'):
        rel_path = parsed.path.removeprefix('/generated/images/')
        content_type = mimetypes.guess_type(rel_path)[0] or 'application/octet-stream'
        send_file(handler, GENERATED_IMAGES_DIR / rel_path, content_type, root=GENERATED_IMAGES_DIR)
        return True
    if parsed.path == '/api/status':
        include_logs = str((params.get('include_logs') or ['0'])[0] or '').strip().lower() in ('1', 'true', 'yes')
        send_json(handler, {'ok': True, 'status': current_status(include_logs=include_logs)})
        return True
    if parsed.path == '/api/terminals':
        send_json(handler, {'ok': True, 'items': list_terminals()})
        return True
    if parsed.path == '/api/terminals/output':
        try:
            item = read_terminal((params.get('id') or [''])[0], (params.get('offset') or ['0'])[0])
            send_json(handler, {'ok': True, **item})
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=404)
        return True
    if parsed.path == '/api/newapi-dashboard':
        status = current_status()
        auth_state = load_state()
        auth_items = list_auth_files()
        selected_auth_refs = auth_state.get('selected_auth_refs') or []
        provider_models = get_configured_provider_models(include_override_only=False)
        force_refresh = str((params.get('refresh') or [''])[0] or '').strip().lower() in ('1', 'true', 'yes')
        cache = refresh_observability_cache(force=True) if force_refresh else ensure_observability_cache()
        events = list(cache.get('events') or [])
        clients = list(cache.get('clients') or [])
        auth_health = list(cache.get('auth_health') or [])
        total_tokens = 0
        success_count = 0
        provider_counts = {}
        for event in events:
            try:
                total_tokens += int(event.get('total_tokens') or 0)
            except Exception:
                pass
            if event.get('success'):
                success_count += 1
            provider = str(event.get('inferred_provider') or 'unknown').strip() or 'unknown'
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
        model_count = 0
        for provider in provider_models:
            rows = provider.get('rows') if isinstance(provider, dict) else []
            if isinstance(rows, list):
                model_count += len(rows)
        send_json(handler, {
            'ok': True,
            'item': {
                'status': status,
                'account': {
                    'balance': 999998.99,
                    'currency': 'USD',
                    'selected_auth_count': len(selected_auth_refs),
                    'auth_count': len(auth_items),
                },
                'usage': {
                    'request_count': len(events),
                    'success_count': success_count,
                    'total_tokens': total_tokens,
                    'estimated_cost': round(total_tokens / 12500, 4),
                    'client_count': len(clients),
                    'model_count': model_count,
                },
                'provider_counts': provider_counts,
                'auth_health_count': len(auth_health),
                'cached': bool(cache.get('ready')),
                'refreshed_at': cache.get('refreshed_at') or 0,
            },
        })
        return True
    if parsed.path == '/api/auth-files':
        state = load_state()
        items_snapshot = list_auth_files()
        enabled_refs = [item.get('id') for item in items_snapshot if item.get('id')]
        enabled_names = [item.get('name') for item in items_snapshot if item.get('name')]
        state['selected_auth_refs'] = enabled_refs
        state['selected_auth_ref'] = enabled_refs[0] if enabled_refs else None
        state['selected_auths'] = enabled_names
        state['selected_auth'] = enabled_names[0] if enabled_names else None
        save_state(state)

        send_json(handler, {
            'ok': True,
            'pool_mode': 'storage_auth',
            'items': items_snapshot,
            'selected_auth': state.get('selected_auth'),
            'selected_auth_ref': state.get('selected_auth_ref'),
            'selected_auths': state.get('selected_auths') or [],
            'selected_auth_refs': state.get('selected_auth_refs') or [],
        })
        return True
    if parsed.path == '/api/provider-models':
        params = parse_qs(parsed.query)
        runtime_only = str(params.get('runtime', ['0'])[0]).strip().lower() in ('1', 'true', 'yes')
        runtime_state = str(params.get('runtime_state', ['0'])[0]).strip().lower() in ('1', 'true', 'yes')
        provider_filter = str(params.get('provider', [''])[0] or '').strip().lower()
        providers_only = str(params.get('providers_only', ['0'])[0]).strip().lower() in ('1', 'true', 'yes')
        items = get_configured_provider_models(include_override_only=False)
        if provider_filter:
            items = [
                item for item in items
                if str(item.get('lookup_provider') or item.get('provider') or '').strip().lower() == provider_filter
            ]
        if providers_only:
            items = [
                {
                    'provider': item.get('provider'),
                    'lookup_provider': item.get('lookup_provider') or item.get('provider'),
                    'row_count': len(item.get('rows') or []),
                }
                for item in items
            ]
            send_json(handler, {
                'ok': True,
                'items': items,
                'providers_only': True,
                'runtime_only': False,
                'runtime_state': False,
                'runtime_loaded': False,
                'runtime_model_ids': [],
            })
            return True
        runtime_loaded = False
        runtime_model_ids = []
        if runtime_only or runtime_state:
            runtime_query = query_models()
            runtime_body = runtime_query.get('body') if isinstance(runtime_query, dict) else {}
            runtime_items = runtime_body.get('data') if isinstance(runtime_body, dict) else []
            if isinstance(runtime_items, list):
                runtime_model_ids = [
                    str(model.get('id') or '').strip()
                    for model in runtime_items
                    if isinstance(model, dict) and str(model.get('id') or '').strip()
                ]
                if runtime_only:
                    items = filter_provider_models_by_runtime(items, runtime_model_ids)
                else:
                    items = annotate_provider_models_runtime(items, runtime_model_ids)
                runtime_loaded = True
        send_json(handler, {
            'ok': True,
            'items': items,
            'runtime_only': runtime_only,
            'runtime_state': runtime_state,
            'runtime_loaded': runtime_loaded,
            'runtime_model_ids': runtime_model_ids if (runtime_only or runtime_state) else [],
        })
        return True
    if parsed.path == '/api/manual-provider-presets':
        send_json(handler, {'ok': True, 'items': get_manual_provider_presets()})
        return True
    if parsed.path == '/api/image-test-candidates':
        send_json(handler, _image_test_candidates())
        return True
    if parsed.path == '/api/provider-model-test-state':
        send_json(handler, get_provider_model_test_state())
        return True
    if parsed.path == '/api/request-events':
        params = parse_qs(parsed.query)
        try:
            limit = max(1, min(1000, int((params.get('limit') or ['50'])[0] or 50)))
        except Exception:
            limit = 50
        try:
            offset = max(0, int((params.get('offset') or ['0'])[0] or 0))
        except Exception:
            offset = 0
        refresh = str((params.get('refresh') or [''])[0] or '').strip().lower() in ('1', 'true', 'yes')
        cache = refresh_observability_cache(force=True) if refresh else ensure_observability_cache()
        items = cache.get('events') or []
        ip_filter = str((params.get('ip') or [''])[0] or '').strip().lower()
        model_filter = str((params.get('model') or [''])[0] or '').strip().lower()
        provider_filter = str((params.get('provider') or [''])[0] or '').strip().lower()
        status_filter = str((params.get('status') or [''])[0] or '').strip()
        success_filter = str((params.get('success') or [''])[0] or '').strip().lower()
        include_models = str((params.get('include_models') or [''])[0] or '').strip().lower() in ('1', 'true', 'yes')
        filtered = []
        for item in items:
            item_path = str(item.get('path') or '').strip()
            if not include_models and item_path.split('?', 1)[0].rstrip('/') == '/v1/models':
                continue
            if ip_filter and ip_filter not in str(item.get('client_ip') or '').strip().lower():
                continue
            model_text = ' '.join([
                str(item.get('requested_model') or '').strip().lower(),
                str(item.get('routed_model') or '').strip().lower(),
            ]).strip()
            if model_filter and model_filter not in model_text:
                continue
            if provider_filter and provider_filter != str(item.get('inferred_provider') or '').strip().lower():
                continue
            if status_filter and status_filter != str(item.get('status_code') or ''):
                continue
            if success_filter in ('true', 'false'):
                expected = success_filter == 'true'
                if bool(item.get('success')) != expected:
                    continue
            filtered.append(item)
        total = len(filtered)
        send_json(handler, {
            'ok': True,
            'items': filtered[offset:offset + limit],
            'total': total,
            'cached': bool(cache.get('ready')),
            'refreshed_at': cache.get('refreshed_at') or 0,
        })
        return True
    if parsed.path == '/api/request-clients':
        params = parse_qs(parsed.query)
        try:
            limit = max(1, min(500, int((params.get('limit') or ['100'])[0] or 100)))
        except Exception:
            limit = 100
        cache = ensure_observability_cache()
        # 客户端列表合并最近窗口 + 累积统计，避免某些 Key 只因最近没请求就消失
        events = list(cache.get('events') or [])
        items = summarize_clients(events, get_cumulative_stats())[:limit]
        send_json(handler, {
            'ok': True,
            'items': items,
            'cached': bool(cache.get('ready')),
            'refreshed_at': cache.get('refreshed_at') or 0,
        })
        return True
    if parsed.path == '/api/model-health':
        provider_models = get_configured_provider_models(include_override_only=False)
        params = parse_qs(parsed.query)
        include_runtime = str((params.get('runtime') or ['0'])[0] or '').strip().lower() in ('1', 'true', 'yes')
        runtime_model_ids = []
        if include_runtime:
            runtime_query = query_models()
            runtime_body = runtime_query.get('body') if isinstance(runtime_query, dict) else {}
            runtime_items = runtime_body.get('data') if isinstance(runtime_body, dict) else []
            runtime_model_ids = [
                str(item.get('id') or '').strip()
                for item in runtime_items
                if isinstance(item, dict) and str(item.get('id') or '').strip()
            ]
        events = merge_request_events(parse_proxy_requests(limit=500), parse_precise_request_events(limit=500), parse_error_logs(limit=500), provider_models)
        send_json(handler, {
            'ok': True,
            'items': summarize_models(events, provider_models, get_provider_model_test_state(), runtime_model_ids),
            'runtime_model_ids': runtime_model_ids,
            'runtime_loaded': include_runtime,
        })
        return True
    if parsed.path == '/api/model-test-stats':
        params = parse_qs(parsed.query)
        try:
            limit = max(1, min(2000, int((params.get('limit') or ['500'])[0] or 500)))
        except Exception:
            limit = 500
        # include override-only providers so historical/deleted mappings can still be attributed
        provider_models = get_configured_provider_models(include_override_only=True)
        force_refresh = str((params.get('refresh') or [''])[0] or '').strip().lower() in ('1', 'true', 'yes')
        cache = refresh_observability_cache(force=True) if force_refresh else ensure_observability_cache()
        events = list(cache.get('events') or [])[:limit]
        rows = summarize_model_test_stats(events, provider_models, get_provider_model_test_state(), limit=limit)

        # 合并累积 token，并为仅出现在历史累计里的模型尽量反查 provider
        try:
            cumulative = get_cumulative_stats()
            rows = merge_cumulative_model_test_stats(rows, cumulative.get('by_model') or {}, provider_models)
        except Exception:
            pass

        send_json(handler, {
            'ok': True,
            'items': rows,
            'limit': limit,
            'cached': bool(cache.get('ready')),
            'refreshed_at': cache.get('refreshed_at') or 0,
        })
        return True
    if parsed.path == '/api/auth-health':
        params = parse_qs(parsed.query)
        try:
            limit = max(1, min(500, int((params.get('limit') or ['100'])[0] or 100)))
        except Exception:
            limit = 100
        cache = ensure_observability_cache()
        items = list(cache.get('auth_health') or [])[:limit]
        send_json(handler, {
            'ok': True,
            'items': items,
            'cached': bool(cache.get('ready')),
            'refreshed_at': cache.get('refreshed_at') or 0,
        })
        return True
    if parsed.path == '/api/route-strategy':
        state = load_state()
        send_json(handler, {
            'ok': True,
            'item': normalize_route_strategy(state.get('route_strategy')),
        })
        return True
    if parsed.path == '/api/aggregate-models':
        send_json(handler, {
            'ok': True,
            'items': get_configured_aggregate_models(),
        })
        return True
    if parsed.path == '/api/aggregate-route-health':
        send_json(handler, get_aggregate_route_health())
        return True
    if parsed.path == '/api/model-proxy-settings':
        send_json(handler, {
            'ok': True,
            'item': get_model_proxy_settings(),
        })
        return True
    if parsed.path == '/api/model-thinking-configs':
        configs = load_model_thinking_configs()
        send_json(handler, {
            'ok': True,
            'candidates': collect_thinking_candidates(),
            'all_models': collect_all_configured_models(),
            'configs': configs.get('configs', {}),
            'updated_at': configs.get('updated_at', 0),
        })
        return True
    if parsed.path == '/api/model-route-preview':
        model_id = (parse_qs(parsed.query).get('model', [''])[0] or '').strip()
        try:
            send_json(handler, {'ok': True, 'item': get_model_route_preview(model_id)})
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
        return True
    if parsed.path == '/api/tool-output':
        send_json(handler, {'ok': True, **get_tool_outputs()})
        return True
    if parsed.path == '/api/query-models':
        send_json(handler, query_models())
        return True
    if parsed.path == '/api/test-proxy':
        send_json(handler, test_proxy())
        return True
    if parsed.path == '/api/cooldown-status':
        provider_models = get_configured_provider_models(include_override_only=False)
        test_state = get_provider_model_test_state()
        results = test_state.get('results') or {}
        strategy = _current_route_strategy()
        now_ts = int(time.time())

        cooldown_items = []
        # Flatten provider models to search for cooldowns
        for p in provider_models:
            provider_name = p.get('provider')
            for row in p.get('rows') or []:
                call_id = row.get('call_id') or row.get('alias') or row.get('name')
                if not call_id:
                    continue

                res = results.get(call_id)
                if not res or res.get('available'):
                    continue

                # Check if it's actually in cooldown
                tested_at = int(res.get('tested_at') or 0)
                from backend.auth import _model_failure_cooldown_seconds
                retry_after = _model_failure_cooldown_seconds(res, strategy)
                if retry_after <= 0:
                    continue

                next_retry_ts = tested_at + retry_after
                if now_ts >= next_retry_ts:
                    continue # Cooldown expired

                from datetime import datetime
                next_retry_after = datetime.fromtimestamp(next_retry_ts).strftime('%Y-%m-%d %H:%M:%S')

                cooldown_items.append({
                    'provider': provider_name,
                    'model': row.get('name'),
                    'auth_label': row.get('alias') or row.get('name'),
                    'auth_id': row.get('auth_id') or row.get('auth_file'),
                    'auth_file': row.get('auth_file'),
                    'email': row.get('email') or '-',
                    'reason': res.get('failure_kind') or 'unknown',
                    'next_retry_ts': next_retry_ts,
                    'next_retry_after': next_retry_after,
                    'remaining_seconds': next_retry_ts - now_ts
                })

        send_json(handler, {'ok': True, 'items': cooldown_items})
        return True
    if parsed.path == '/api/virtual-keys':
        items = list_api_keys()
        send_json(handler, {'ok': True, 'items': items})
        return True
    if parsed.path == '/api/network-access':
        status = current_status()
        state = load_state()
        exposure_enabled = bool(state.get('exposure_enabled'))
        lan_ip = status.get('lan_ip')
        network_ips = status.get('network_ips') or []
        recommended_external_ip = status.get('recommended_external_ip') or {}
        recommended_ip = recommended_external_ip.get('ip') or lan_ip
        proxy_running = bool(status.get('proxy_running'))
        api_key = status.get('api_key') or 'cliproxyapi'

        base_url_local = 'http://127.0.0.1:8317'
        base_url_lan = f'http://{recommended_ip}:8317' if recommended_ip else None
        dashboard_url = status.get('dashboard_lan_url')

        virtual_keys = list_api_keys()
        active_keys = [k for k in virtual_keys if k.get('enabled') and not k.get('expired')]

        send_json(handler, {
            'ok': True,
            'item': {
                'exposure_enabled': exposure_enabled,
                'proxy_running': proxy_running,
                'lan_ip': lan_ip,
                'network_ips': network_ips,
                'recommended_external_ip': recommended_external_ip,
                'default_route_ip': status.get('default_route_ip'),
                'base_url_local': base_url_local,
                'base_url_lan': base_url_lan,
                'admin_api_key': api_key,
                'virtual_keys_total': len(virtual_keys),
                'virtual_keys_active': len(active_keys),
                'dashboard_url': dashboard_url,
                'dashboard_bind_host': status.get('dashboard_bind_host'),
                'dashboard_port': status.get('dashboard_port'),
                'dashboard_remote_accessible': bool(status.get('dashboard_remote_accessible')),
                'firewall': firewall_access_status(),
            },
        })
        return True
    if parsed.path == '/api/firewall-access':
        params = parse_qs(parsed.query)
        try:
            ports = normalize_firewall_ports(params.get('ports') or [])
            protocols = normalize_firewall_protocols(params.get('protocols') or params.get('protocol') or ['TCP'])
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        send_json(handler, {'ok': True, 'item': custom_firewall_status(ports, protocols)})
        return True
    if parsed.path == '/api/port-bindings':
        send_json(handler, {'ok': True, 'item': port_binding_status(), 'ip_helper': ip_helper_status()})
        return True
    if parsed.path == '/api/ip-helper':
        send_json(handler, {'ok': True, 'item': ip_helper_status()})
        return True
    if parsed.path == '/api/security-audit':
        include_paths = str(parse_qs(parsed.query).get('include_paths', ['0'])[0]).strip().lower() in ('1', 'true', 'yes')
        send_json(handler, {'ok': True, 'report': generate_security_report(include_paths=include_paths)})
        return True
    if parsed.path == '/api/advanced-config':
        state = load_state()
        send_json(handler, {'ok': True, 'item': {
            'disable_cooling': state.get('disable_cooling', False),
            'disable_image_generation': state.get('disable_image_generation', 'off'),
            'session_affinity_enabled': state.get('session_affinity_enabled', False),
            'session_affinity_ttl': state.get('session_affinity_ttl', '1h'),
            'auth_auto_refresh_workers': state.get('auth_auto_refresh_workers', 16),
            'local_model': state.get('local_model', False),
            'ws_auth': state.get('ws_auth', False),
            'commercial_mode': state.get('commercial_mode', False),
        }})
        return True
    if parsed.path == '/api/cloaking-config':
        state = load_state()
        from backend.paths import POOL_AUTH_DIR
        auth_files = list_auth_files()
        per_auth = {}
        for af in auth_files:
            ref = af.get('id')
            if not ref:
                continue
            try:
                payload = _read_auth_payload(af.get('source_path'))
            except Exception:
                continue
            if isinstance(payload, dict):
                cloak = payload.get('cloak')
                if isinstance(cloak, dict):
                    per_auth[ref] = {
                        'cloak_mode': cloak.get('mode', 'auto'),
                        'cloak_strict_mode': cloak.get('strict_mode', False),
                        'cloak_sensitive_words': cloak.get('sensitive_words', []),
                        'cloak_cache_user_id': cloak.get('cache_user_id', True),
                        'experimental_cch_signing': payload.get('experimental_cch_signing', False),
                    }
        send_json(handler, {'ok': True, 'items': per_auth, 'auth_files': [{'id': af.get('id'), 'name': af.get('name'), 'provider': af.get('provider')} for af in auth_files if af.get('id')]})
        return True
    if parsed.path == '/api/amp-config':
        state = load_state()
        amp_config = state.get('amp_config') or {}
        send_json(handler, {'ok': True, 'item': {
            'amp_upstream_url': amp_config.get('upstream_url', '') or '',
            'amp_upstream_api_key': amp_config.get('upstream_api_key', '') or '',
            'amp_upstream_api_key_set': bool(amp_config.get('upstream_api_key', '')),
            'amp_restrict_localhost': amp_config.get('restrict_localhost', True),
            'amp_force_model_mappings': amp_config.get('force_mappings', False),
            'amp_model_mappings': amp_config.get('model_mappings', []) or [],
        }})
        return True
    if parsed.path == '/api/storage-config':
        from backend.proxy_env import load_proxy_env, mask_sensitive
        stored = load_proxy_env()
        masked = mask_sensitive(stored)
        send_json(handler, {'ok': True, 'item': masked})
        return True
    if parsed.path == '/api/home-config':
        from backend.proxy_env import load_proxy_env
        state = load_state()
        stored = load_proxy_env()
        home_jwt_set = bool(stored.get('HOME_JWT', ''))
        send_json(handler, {'ok': True, 'item': {
            'home_jwt_set': home_jwt_set,
            'home_disable_cluster_discovery': state.get('home_disable_cluster_discovery', False),
        }})
        return True
    if parsed.path == '/api/data/export':
        try:
            from backend.data_transfer import export_all
            result = export_all()
            send_json(handler, result)
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Export failed: {e}'}, status=500)
        return True
    if parsed.path == '/api/settings':
        from backend.settings import get_settings
        send_json(handler, get_settings())
        return True
    if parsed.path == '/api/version':
        from backend.settings import get_version_info
        send_json(handler, get_version_info())
        return True
    if parsed.path == '/api/check-updates':
        from backend.settings import check_for_updates
        send_json(handler, check_for_updates())
        return True
    if parsed.path == '/api/download-update':
        from backend.settings import download_update
        send_json(handler, download_update())
        return True
    if parsed.path == '/api/cumulative-stats':
        send_json(handler, {'ok': True, 'stats': get_cumulative_stats()})
        return True
    if parsed.path == '/api/auth/check':
        from backend.access_auth import password_is_set, validate_token, extract_token_from_handler
        is_set = password_is_set()
        token = extract_token_from_handler(handler)
        authenticated = bool(token and validate_token(token))
        send_json(handler, {'ok': True, 'password_set': is_set, 'authenticated': authenticated})
        return True
    if parsed.path == '/api/system-proxy':
        try:
            send_json(handler, get_system_proxy_status())
        except Exception as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=500)
        return True
    if parsed.path == '/api/grok2api/system-proxy':
        # Ask the running grok2api process what port *it* currently resolved.
        # Do not reuse /api/system-proxy (OS setting); those can diverge.
        try:
            import json as _json
            import urllib.error
            import urllib.request

            url = f'http://127.0.0.1:{grok2api_port()}/system-proxy'
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                body = resp.read().decode('utf-8', errors='replace')
            payload = _json.loads(body or '{}')
            if not isinstance(payload, dict):
                payload = {}
            send_json(handler, {
                'ok': True,
                'source': 'grok2api-process',
                'reachable': True,
                'enabled': bool(payload.get('enabled')),
                'port': int(payload.get('port') or 0) or None,
                'proxy_url': str(payload.get('proxyURL') or payload.get('proxy_url') or ''),
                'raw': payload,
            })
        except Exception as e:
            send_json(handler, {
                'ok': False,
                'source': 'grok2api-process',
                'reachable': False,
                'enabled': False,
                'port': None,
                'proxy_url': '',
                'message': f'无法读取 grok2api 实际系统代理端口: {e}',
            })
        return True
    return False
