from backend.auth import create_manual_auth_entry, create_manual_auth_bundle_entry, list_auth_files, build_auth_ref, set_provider_model_override, delete_provider_model_override, create_custom_aggregate_alias, add_custom_aggregate_alias_members, set_custom_aggregate_alias_members, delete_custom_aggregate_alias, move_custom_aggregate_alias, rename_custom_aggregate_alias, delete_auth_entries, save_model_proxy_rules, rebuild_runtime_config_from_state, get_configured_provider_models, reorder_custom_aggregate_aliases
from backend.api_keys import create_api_key, update_api_key, delete_api_key, reset_api_key_usage, reveal_api_key
from backend.state import load_state, save_state, normalize_route_strategy
from backend.processes import start_device_login, stop_device_login, start_proxy, stop_proxy, restart_proxy, start_project, start_oauth_manager, stop_oauth_manager, current_status, ensure_firewall_access, ensure_custom_firewall_ports, remove_custom_firewall_ports, ensure_external_firewall_ports, remove_external_firewall_ports, ensure_port_bindings, remove_port_bindings, set_ip_helper_service, stop_dashboard_panel, restart_dashboard_panel
from backend.tools import run_tool, stop_tool, test_provider_models, test_image_models, test_auth_entry, queue_provider_model_tests, clear_provider_model_test_state, stop_provider_model_tests, run_storage_cleanup, _proxy_request
from backend.terminals import open_terminal, open_desktop_terminal, close_terminal, list_terminals, write_terminal, resize_terminal
from backend.routes.helpers import send_json


def handle_post(handler, parsed, data):
    if parsed.path == '/api/terminals/open':
        try:
            item = open_terminal(
                kind=(data or {}).get('kind') if isinstance(data, dict) else 'powershell',
                cwd=(data or {}).get('cwd') if isinstance(data, dict) else None,
            )
            send_json(handler, {'ok': True, 'item': item, 'items': list_terminals()})
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'打开终端失败: {e}'}, status=500)
        return True
    if parsed.path == '/api/terminals/open-desktop':
        try:
            item = open_desktop_terminal(
                kind=(data or {}).get('kind') if isinstance(data, dict) else 'powershell',
                cwd=(data or {}).get('cwd') if isinstance(data, dict) else None,
            )
            send_json(handler, {'ok': True, 'item': item})
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'打开桌面终端失败: {e}'}, status=500)
        return True
    if parsed.path == '/api/terminals/close':
        try:
            result = close_terminal((data or {}).get('id') if isinstance(data, dict) else '')
            send_json(handler, {'ok': True, 'item': result, 'items': list_terminals()})
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=404)
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'关闭终端失败: {e}'}, status=500)
        return True
    if parsed.path == '/api/terminals/input':
        try:
            result = write_terminal(
                (data or {}).get('id') if isinstance(data, dict) else '',
                (data or {}).get('text') if isinstance(data, dict) else '',
            )
            send_json(handler, {'ok': True, 'item': result})
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=404)
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'写入终端失败: {e}'}, status=500)
        return True

    if parsed.path == '/api/terminals/resize':
        try:
            result = resize_terminal(
                (data or {}).get('id') if isinstance(data, dict) else '',
                (data or {}).get('rows') if isinstance(data, dict) else None,
                (data or {}).get('cols') if isinstance(data, dict) else None,
            )
            send_json(handler, {'ok': True, 'item': result})
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=404)
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'调整终端大小失败: {e}'}, status=500)
        return True

    if parsed.path == '/api/move-auth-in-pool':
        send_json(handler, {'ok': True, 'message': 'Auth is now controlled by files in storage/auth; order changes are not used.'})
        return True

    if parsed.path == '/api/delete-auths':
        ids = data.get('ids') if isinstance(data, dict) else None
        if not isinstance(ids, list):
            send_json(handler, {'ok': False, 'message': 'Missing auth file ids.'}, status=400)
            return True
        try:
            result = delete_auth_entries(ids)
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to delete auth files: {e}'}, status=500)
            return True

        deleted_refs = [ref for ref in (result.get('deleted_auth_refs') or []) if ref]
        missing_refs = [ref for ref in (result.get('missing_auth_refs') or []) if ref]
        state = load_state()
        remaining_refs = [ref for ref in (state.get('selected_auth_refs') or []) if ref and ref not in deleted_refs]
        remaining_items = [item for item in list_auth_files() if item.get('id') in remaining_refs]
        state['selected_auth'] = remaining_items[0].get('name') if remaining_items else None
        state['selected_auth_ref'] = remaining_items[0].get('id') if remaining_items else None
        state['selected_auths'] = [item.get('name') for item in remaining_items]
        state['selected_auth_refs'] = [item.get('id') for item in remaining_items]
        rebuild_result = rebuild_runtime_config_from_state(state) if deleted_refs else {'rebuilt': False, 'reason': 'no_deleted_auths'}
        save_state(state)

        send_json(handler, {
            'ok': True,
            'message': f'Deleted {len(deleted_refs)} auth file(s).' + (f' Missing: {len(missing_refs)}.' if missing_refs else ''),
            'deleted_auth_refs': deleted_refs,
            'missing_auth_refs': missing_refs,
            'selected_auth': state['selected_auth'],
            'selected_auth_ref': state['selected_auth_ref'],
            'selected_auths': state['selected_auths'],
            'selected_auth_refs': state['selected_auth_refs'],
            'runtime_rebuild': rebuild_result,
        })
        return True
    if parsed.path == '/api/create-manual-auth':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        base_url = data.get('base_url')
        model = data.get('model')
        raw_models = data.get('models')
        api_key = data.get('api_key')
        provider = data.get('provider')
        remark = data.get('remark')
        select_after_create = bool(data.get('select_after_create'))
        test_after_create = bool(data.get('test_after_create'))
        try:
            models = []
            if isinstance(raw_models, list):
                for item in raw_models:
                    value = str(item or '').strip()
                    if value and value not in models:
                        models.append(value)
            if not models and isinstance(model, str):
                value = model.strip()
                if value:
                    models.append(value)
            if len(models) > 1:
                auth_info = create_manual_auth_bundle_entry(base_url, models, api_key, provider, remark)
            else:
                auth_info = create_manual_auth_entry(base_url, models[0] if models else model, api_key, provider, remark)

            rebuild = {'rebuilt': False, 'reason': 'not_requested'}
            proxy_restart = {'ok': False, 'reason': 'not_requested'}
            selected_auth_refs = []
            if select_after_create:
                state = load_state()
                selected_auth_refs = [str(ref or '').strip() for ref in (state.get('selected_auth_refs') or []) if str(ref or '').strip()]
                auth_items = list_auth_files()
                created_path = str(auth_info.get('path') or '').strip()
                created_name = str(auth_info.get('name') or '').strip()
                created_item = next(
                    (
                        item for item in auth_items
                        if str(item.get('id') or '').strip() == str(auth_info.get('id') or '').strip()
                        or (created_path and str(item.get('path') or '').strip() == created_path)
                        or (created_name and str(item.get('name') or '').strip() == created_name)
                    ),
                    None,
                )
                auth_ref = str((created_item or auth_info).get('id') or '').strip()
                if auth_ref and auth_ref not in selected_auth_refs:
                    selected_auth_refs.append(auth_ref)
                item_map = {item.get('id'): item for item in auth_items if item.get('id')}
                selected_items = [item_map[ref] for ref in selected_auth_refs if ref in item_map]
                state['selected_auth_refs'] = [item.get('id') for item in selected_items]
                state['selected_auths'] = [item.get('name') for item in selected_items]
                state['selected_auth_ref'] = state['selected_auth_refs'][0] if state['selected_auth_refs'] else None
                state['selected_auth'] = state['selected_auths'][0] if state['selected_auths'] else None
                save_state(state)
                rebuild = rebuild_runtime_config_from_state(state)
                if test_after_create and rebuild.get('rebuilt') and current_status().get('proxy_running'):
                    proxy_restart = restart_proxy()

            test_result = {'ok': False, 'reason': 'not_requested'}
            call_models = auth_info.get('models') if isinstance(auth_info.get('models'), list) else []
            call_ids = []
            for item in call_models or models:
                value = str(item.get('alias') if isinstance(item, dict) else item or '').strip()
                if value and value not in call_ids:
                    call_ids.append(value)
            if test_after_create and call_ids:
                test_result = queue_provider_model_tests(call_ids)

            safe_auth = dict(auth_info)
            safe_auth.pop('api_key', None)
            send_json(handler, {
                'ok': True,
                'message': 'Manual auth entry created successfully.',
                'auth': safe_auth,
                'runtime_rebuilt': bool(rebuild.get('rebuilt')),
                'runtime_validation': rebuild.get('validation'),
                'proxy_restart': proxy_restart,
                'test_queued': bool(test_result.get('ok')),
                'test_result': test_result,
                'selected_auth_refs': selected_auth_refs,
            })
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to create manual auth: {e}'}, status=500)
        return True

    if parsed.path == '/api/start-device-login':
        send_json(handler, start_device_login())
        return True
    if parsed.path == '/api/stop-device-login':
        send_json(handler, stop_device_login())
        return True
    if parsed.path == '/api/select-auths':
        ids = data.get('ids') if isinstance(data, dict) else None
        if not isinstance(ids, list):
            send_json(handler, {'ok': False, 'message': 'Missing auth file ids.'}, status=400)
            return True

        items = list_auth_files()
        item_map = {item.get('id'): item for item in items if item.get('id')}
        selected_items = []
        for auth_id in ids:
            item = item_map.get(auth_id)
            if item and item not in selected_items:
                selected_items.append(item)

        if not selected_items:
            state = load_state()
            state['selected_auth'] = None
            state['selected_auth_ref'] = None
            state['selected_auths'] = []
            state['selected_auth_refs'] = []
            save_state(state)
            send_json(handler, {
                'ok': True,
                'message': 'Auth is controlled by storage/auth files. Delete or move files out of storage/auth to disable them.',
                'selected_auth': None,
                'selected_auth_ref': None,
                'selected_auths': [],
                'selected_auth_refs': [],
            })
            return True

        state = load_state()
        state['selected_auth'] = selected_items[0].get('name')
        state['selected_auth_ref'] = selected_items[0].get('id')
        state['selected_auths'] = [item.get('name') for item in selected_items]
        state['selected_auth_refs'] = [item.get('id') for item in selected_items]
        save_state(state)

        status = current_status()
        message = 'Auth is controlled by storage/auth files. Add/delete JSON files to change active accounts.'

        send_json(handler, {
            'ok': True,
            'message': message,
            'selected_auth': state['selected_auth'],
            'selected_auth_ref': state['selected_auth_ref'],
            'selected_auths': state['selected_auths'],
            'selected_auth_refs': state['selected_auth_refs'],
            'restart_required': bool(status.get('restart_required')),
        })
        return True
    if parsed.path == '/api/select-auth':
        auth_id = data.get('id') if isinstance(data, dict) else None
        name = data.get('name') if isinstance(data, dict) else None

        if not auth_id and not name:
            send_json(handler, {'ok': False, 'message': 'Missing auth file id or name.'}, status=400)
            return True

        items = list_auth_files()
        selected_item = None
        if auth_id:
            selected_item = next((item for item in items if item.get('id') == auth_id), None)
        elif name:
            selected_item = next((item for item in items if item.get('id') == build_auth_ref('default', name)), None)
            if not selected_item:
                selected_item = next((item for item in items if item.get('name') == name), None)

        if not selected_item:
            target = auth_id or name
            send_json(handler, {'ok': False, 'message': f'Auth file not found: {target}'}, status=404)
            return True

        state = load_state()
        state['selected_auth'] = selected_item.get('name')
        state['selected_auth_ref'] = selected_item.get('id')
        state['selected_auths'] = [selected_item.get('name')]
        state['selected_auth_refs'] = [selected_item.get('id')]
        save_state(state)

        status = current_status()
        message = 'Auth is controlled by storage/auth files. This selection is display-only.'

        send_json(handler, {
            'ok': True,
            'message': message,
            'selected_auth': selected_item.get('name'),
            'selected_auth_ref': selected_item.get('id'),
            'selected_auths': state['selected_auths'],
            'selected_auth_refs': state['selected_auth_refs'],
            'restart_required': bool(status.get('restart_required')),
        })
        return True
    if parsed.path == '/api/provider-model-override':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        try:
            item = set_provider_model_override(
                provider=data.get('provider', ''),
                upstream_id=data.get('upstream_id', ''),
                call_id=data.get('call_id', ''),
                target_provider=data.get('target_provider', ''),
                target_upstream_id=data.get('target_upstream_id', ''),
            )
            rebuild = rebuild_runtime_config_from_state(load_state())
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to save model mapping: {e}'}, status=500)
            return True
        message = f'Saved model mapping: {item.get("provider")} / {item.get("upstream_id")}'
        if not rebuild.get('rebuilt'):
            message += '. No storage/auth account files to rebuild right now.'
        send_json(handler, {
            'ok': True,
            'message': message,
            'item': item,
            'runtime_rebuilt': bool(rebuild.get('rebuilt')),
            'runtime_validation': rebuild.get('validation'),
        })
        return True
    if parsed.path == '/api/provider-model-delete':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        try:
            item = delete_provider_model_override(
                provider=data.get('provider', ''),
                upstream_id=data.get('upstream_id', ''),
                call_id=data.get('call_id'),
            )
            rebuild = rebuild_runtime_config_from_state(load_state())
        except ValueError as e:

            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to delete model mapping: {e}'}, status=500)
            return True
        message = f'Deleted model mapping: {item.get("provider")} / {item.get("upstream_id")}'
        if not rebuild.get('rebuilt'):
            message += '. No storage/auth account files to rebuild right now.'
        send_json(handler, {
            'ok': True,
            'message': message,
            'item': item,
            'runtime_rebuilt': bool(rebuild.get('rebuilt')),
            'runtime_validation': rebuild.get('validation'),
        })
        return True
    if parsed.path == '/api/model-proxy-settings':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        try:
            item = save_model_proxy_rules(data.get('rules') or [])
            rebuild = rebuild_runtime_config_from_state(load_state())
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to save model proxy settings: {e}'}, status=500)
            return True
        message = 'Saved model proxy settings.'
        if not rebuild.get('rebuilt'):
            message += ' No storage/auth account files to rebuild right now.'
        send_json(handler, {
            'ok': True,
            'message': message,
            'item': item,
            'runtime_rebuilt': bool(rebuild.get('rebuilt')),
            'runtime_validation': rebuild.get('validation'),
        })
        return True
    if parsed.path == '/api/aggregate-models':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        action = str(data.get('action') or '').strip().lower()
        try:
            if action == 'create':
                item = create_custom_aggregate_alias(data.get('alias_id', ''))
                message = f'Created aggregate ID: {item.get("alias_id")}'
            elif action == 'delete':
                item = delete_custom_aggregate_alias(data.get('alias_id', ''))
                message = f'Deleted aggregate ID: {item.get("alias_id")}'
            elif action == 'move':
                item = move_custom_aggregate_alias(
                    data.get('alias_id', ''),
                    data.get('direction', 0),
                )
                message = f'Saved aggregate order: {item.get("alias_id")}'
            elif action == 'reorder':
                ordered_ids = data.get('ordered_ids')
                if not isinstance(ordered_ids, list):
                    send_json(handler, {'ok': False, 'message': 'ordered_ids must be a list.'}, status=400)
                    return True
                item = reorder_custom_aggregate_aliases(ordered_ids)
                message = f'Saved aggregate ordering'
            elif action == 'rename':
                item = rename_custom_aggregate_alias(
                    data.get('alias_id', ''),
                    data.get('new_alias_id', ''),
                )
                message = f'Renamed aggregate ID: {item.get("old_alias_id")} -> {item.get("alias_id")}'
            elif action == 'add_members':
                item = add_custom_aggregate_alias_members(
                    data.get('alias_id', ''),
                    data.get('members') if isinstance(data.get('members'), list) else [],
                )
                message = f'Updated aggregate ID: {item.get("alias_id")}'
            elif action == 'set_members':
                item = set_custom_aggregate_alias_members(
                    data.get('alias_id', ''),
                    data.get('members') if isinstance(data.get('members'), list) else [],
                )
                message = f'Saved aggregate order: {item.get("alias_id")}'
            else:
                send_json(handler, {'ok': False, 'message': 'Unsupported aggregate action.'}, status=400)
                return True
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to update aggregate IDs: {e}'}, status=500)
            return True
        status_before_apply = current_status()
        rebuild = rebuild_runtime_config_from_state(load_state())
        apply_result = {'applied': False, 'restarted': False}
        skip_restart = bool(data.get('skip_restart')) if isinstance(data, dict) else False
        if not rebuild.get('rebuilt'):
            message += '. No storage/auth account files to rebuild right now.'
        elif status_before_apply.get('proxy_running') and not skip_restart:
            apply_result = restart_proxy()
            apply_result['applied'] = bool(apply_result.get('ok'))
            apply_result['restarted'] = bool(apply_result.get('ok'))
            if apply_result.get('ok'):
                message += '. Runtime applied to running proxy.'
            else:
                message += f'. Runtime config was rebuilt, but proxy restart failed: {apply_result.get("message") or "unknown error"}'
        elif skip_restart:
            message += '. Runtime config rebuilt; restart skipped.'
        else:
            message += '. Runtime config rebuilt; start proxy to apply.'
        send_json(handler, {
            'ok': True,
            'message': message,
            'item': item,
            'runtime_rebuilt': bool(rebuild.get('rebuilt')),
            'runtime_applied': bool(apply_result.get('applied')),
            'proxy_restarted': bool(apply_result.get('restarted')),
            'apply_result': apply_result,
            'runtime_validation': rebuild.get('validation'),
        })
        return True
    if parsed.path == '/api/test-provider-models':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        model_ids = data.get('model_ids')
        if not isinstance(model_ids, list):
            send_json(handler, {'ok': False, 'message': 'model_ids must be a list.'}, status=400)
            return True
        result = test_provider_models(model_ids)
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/test-image-models':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        model_ids = data.get('model_ids')
        if not isinstance(model_ids, list):
            send_json(handler, {'ok': False, 'message': 'model_ids must be a list.'}, status=400)
            return True
        result = test_image_models(model_ids)
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/provider-model-tests':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        action = str(data.get('action') or 'start').strip().lower()
        if action == 'clear':
            result = clear_provider_model_test_state(data.get('model_ids') if isinstance(data.get('model_ids'), list) else None)
            send_json(handler, result)
            return True
        if action == 'stop':
            result = stop_provider_model_tests()
            send_json(handler, result)
            return True
        model_ids = data.get('model_ids')
        if not isinstance(model_ids, list):
            send_json(handler, {'ok': False, 'message': 'model_ids must be a list.'}, status=400)
            return True
        result = queue_provider_model_tests(model_ids)
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/route-strategy':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        state = load_state()
        current = normalize_route_strategy(state.get('route_strategy'))
        update = data.get('item') if isinstance(data.get('item'), dict) else data
        merged = dict(current)
        merged.update({k: update.get(k) for k in current.keys() if k in update})
        state['route_strategy'] = normalize_route_strategy(merged)
        save_state(state)
        rebuild_result = {'rebuilt': False}
        if current_status().get('proxy_running'):
            rebuild_result = rebuild_runtime_config_from_state(state)
        send_json(handler, {
            'ok': True,
            'message': 'Saved route strategy.',
            'item': state['route_strategy'],
            'runtime_config': rebuild_result,
            'restart_required': current_status().get('restart_required'),
            'runtime_validation': rebuild_result.get('validation'),
        })
        return True
    if parsed.path == '/api/test-auth-entry':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        auth_ref = data.get('auth_ref')
        if not auth_ref:
            send_json(handler, {'ok': False, 'message': 'auth_ref is required.'}, status=400)
            return True
        result = test_auth_entry(str(auth_ref))
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True

    if parsed.path == '/api/start-proxy':
        result = start_proxy()
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/start-project':
        result = start_project()
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/stop-proxy':
        send_json(handler, stop_proxy())
        return True
    if parsed.path == '/api/restart-proxy':
        result = restart_proxy()
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/start-oauth-manager':
        result = start_oauth_manager()
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/stop-oauth-manager':
        send_json(handler, stop_oauth_manager())
        return True
    if parsed.path == '/api/clear-cooldown':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True

        auth_id = data.get('auth_id')
        model = data.get('model')
        entries = data.get('entries') # List of {auth_id, model}

        model_ids_to_clear = []

        # If entries is provided, we clear multiple
        target_list = entries if isinstance(entries, list) else ([{'auth_id': auth_id, 'model': model}] if auth_id else [])

        if target_list:
            provider_models = get_configured_provider_models()
            for target in target_list:
                t_auth = target.get('auth_id')
                t_model = target.get('model')

                for p in provider_models:
                    for row in p.get('rows') or []:
                        # Match by auth_id/file and model name
                        if (row.get('auth_id') == t_auth or row.get('auth_file') == t_auth) and (not t_model or row.get('name') == t_model):
                            call_id = row.get('call_id') or row.get('alias') or row.get('name')
                            if call_id and call_id not in model_ids_to_clear:
                                model_ids_to_clear.append(call_id)

        if not model_ids_to_clear and not entries:
            # If no specific IDs found, maybe they want to clear ALL?
            # But the frontend usually sends specific ones.
            send_json(handler, {'ok': False, 'message': 'No matching cooldown entries found.'}, status=404)
            return True

        result = clear_provider_model_test_state(model_ids_to_clear if model_ids_to_clear else None)
        send_json(handler, {'ok': True, 'message': 'Cooldown(s) cleared.', 'cleared_count': len(model_ids_to_clear)})
        return True
    if parsed.path == '/api/enable-exposure':
        state = load_state()
        state['exposure_enabled'] = True
        save_state(state)
        if current_status().get('proxy_running'):
            result = restart_proxy()
            result['message'] = 'Exposure mode enabled. ' + result.get('message', '')
            send_json(handler, result, status=200 if result.get('ok') else 400)
            return True
        send_json(handler, {'ok': True, 'message': 'Exposure mode enabled. Start or restart CLIProxyAPI to apply.'})
        return True
    if parsed.path == '/api/disable-exposure':
        state = load_state()
        state['exposure_enabled'] = False
        save_state(state)
        if current_status().get('proxy_running'):
            result = restart_proxy()
            result['message'] = 'Exposure mode disabled. ' + result.get('message', '')
            send_json(handler, result, status=200 if result.get('ok') else 400)
            return True
        send_json(handler, {'ok': True, 'message': 'Exposure mode disabled. Start or restart CLIProxyAPI to apply.'})
        return True
    if parsed.path == '/api/network-access/firewall/allow':
        elevated = bool(data.get('elevated', True)) if isinstance(data, dict) else True
        result = ensure_firewall_access(elevated=elevated)
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/firewall-access/allow':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        try:
            result = ensure_custom_firewall_ports(
                data.get('ports') or [],
                data.get('protocols') or data.get('protocol') or ['TCP'],
                data.get('remote_addresses') or data.get('remoteAddress') or [],
                elevated=bool(data.get('elevated', True)),
            )
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/firewall-access/remove':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        try:
            result = remove_custom_firewall_ports(data.get('ports') or [], data.get('protocols') or data.get('protocol') or ['TCP'], elevated=bool(data.get('elevated', True)))
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/external-access/allow':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        try:
            result = ensure_external_firewall_ports(
                data.get('ports') or [],
                data.get('protocols') or data.get('protocol') or ['TCP'],
                data.get('remote_addresses') or data.get('remoteAddress') or [],
                elevated=bool(data.get('elevated', True)),
            )
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/external-access/remove':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        try:
            result = remove_external_firewall_ports(
                data.get('ports') or [],
                data.get('protocols') or data.get('protocol') or ['TCP'],
                elevated=bool(data.get('elevated', True)),
            )
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/port-bindings/enable':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        try:
            result = ensure_port_bindings(
                data.get('ports') or [],
                elevated=bool(data.get('elevated', True)),
            )
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/port-bindings/remove':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        try:
            result = remove_port_bindings(data.get('ports') or [], elevated=bool(data.get('elevated', True)))
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/ip-helper':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        try:
            result = set_ip_helper_service(data.get('action'), elevated=bool(data.get('elevated', True)))
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
            return True
        send_json(handler, result, status=200 if result.get('ok') else 400)
        return True
    if parsed.path == '/api/run-tool':
        tool_id = data.get('tool') if isinstance(data, dict) else None
        if not tool_id:
            send_json(handler, {'ok': False, 'message': 'Missing tool id.'}, status=400)
            return True
        result = run_tool(tool_id)
        send_json(handler, result, status=200 if result.get('ok') else 500)
        return True
    if parsed.path == '/api/storage-cleanup':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        result = run_storage_cleanup(
            apply=bool(data.get('apply')),
            include_logs=bool(data.get('include_logs')),
            include_archived_error_logs=bool(data.get('include_archived_error_logs')),
            include_backups=bool(data.get('include_backups')),
            include_generated_images=bool(data.get('include_generated_images')),
            include_old_auth=bool(data.get('include_old_auth')),
        )
        send_json(handler, result, status=200 if result.get('ok') else 500)
        return True
    if parsed.path == '/api/stop-tool':
        tool_id = data.get('tool') if isinstance(data, dict) else None
        if not tool_id:
            send_json(handler, {'ok': False, 'message': 'Missing tool id.'}, status=400)
            return True
        send_json(handler, stop_tool(tool_id))
        return True
    if parsed.path == '/api/dashboard/stop':
        send_json(handler, stop_dashboard_panel())
        return True
    if parsed.path == '/api/dashboard/restart':
        send_json(handler, restart_dashboard_panel())
        return True
    if parsed.path == '/api/chat':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True

        # Proxy request to CLIProxyAPI
        result = _proxy_request('/v1/chat/completions', data)

        if result.get('ok'):
            try:
                import json
                body = json.loads(result.get('body'))
                send_json(handler, body)
            except Exception as e:
                send_json(handler, {'ok': False, 'message': f'Failed to parse proxy response: {e}'}, status=500)
        else:
            status_code = result.get('status_code') or 500
            try:
                import json
                body = json.loads(result.get('body'))
                send_json(handler, body, status=status_code)
            except:
                send_json(handler, {'ok': False, 'message': result.get('error') or result.get('body') or 'Proxy request failed'}, status=status_code)
        return True
    if parsed.path == '/api/virtual-keys':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        action = str(data.get('action') or 'create').strip().lower()
        try:
            if action == 'create':
                result = create_api_key(
                    name=data.get('name', ''),
                    note=data.get('note', ''),
                    allowed_models=data.get('allowed_models'),
                    rate_limit_rpm=data.get('rate_limit_rpm', 0),
                    max_tokens=data.get('max_tokens', 0),
                    max_requests=data.get('max_requests', 0),
                    expires_at=data.get('expires_at', 0),
                )
                send_json(handler, {'ok': True, 'message': f'Created key: {result.get("name", "")}.', 'item': result})
            elif action == 'update':
                result = update_api_key(
                    key_id=data.get('id', ''),
                    name=data.get('name'),
                    note=data.get('note'),
                    enabled=data.get('enabled'),
                    allowed_models=data.get('allowed_models'),
                    rate_limit_rpm=data.get('rate_limit_rpm'),
                    max_tokens=data.get('max_tokens'),
                    max_requests=data.get('max_requests'),
                    expires_at=data.get('expires_at'),
                )
                send_json(handler, {'ok': True, 'message': 'Key updated.', 'item': result})
            elif action == 'delete':
                result = delete_api_key(data.get('id', ''))
                send_json(handler, {'ok': True, 'message': 'Key deleted.', 'item': result})
            elif action == 'reset':
                result = reset_api_key_usage(data.get('id', ''))
                send_json(handler, {'ok': True, 'message': 'Usage reset.', 'item': result})
            elif action == 'reveal':
                result = reveal_api_key(data.get('id', ''))
                send_json(handler, {'ok': True, 'item': result})
            else:
                send_json(handler, {'ok': False, 'message': f'Unknown action: {action}'}, status=400)
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Key operation failed: {e}'}, status=500)
        return True
    if parsed.path == '/api/advanced-config':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        try:
            state = load_state()
            if 'disable_image_generation' in data:
                v = str(data['disable_image_generation'] or 'off').strip().lower()
                if v not in ('off', 'all', 'chat'):
                    raise ValueError('disable_image_generation must be off, all, or chat')
                state['disable_image_generation'] = v
            for key in ('session_affinity_enabled', 'local_model', 'ws_auth', 'commercial_mode'):
                if key in data:
                    state[key] = bool(data[key])
            if 'session_affinity_ttl' in data:
                state['session_affinity_ttl'] = str(data['session_affinity_ttl'] or '1h').strip()
            if 'auth_auto_refresh_workers' in data:
                state['auth_auto_refresh_workers'] = max(1, min(256, int(data['auth_auto_refresh_workers'] or 16)))
            save_state(state)
            rebuild = rebuild_runtime_config_from_state(state)
            send_json(handler, {'ok': True, 'message': 'Advanced config saved.', 'runtime_rebuilt': rebuild.get('rebuilt'), 'restart_required': True})
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to save advanced config: {e}'}, status=500)
        return True
    if parsed.path == '/api/cloaking-config':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        auth_ref = str(data.get('auth_ref') or '').strip()
        if not auth_ref:
            send_json(handler, {'ok': False, 'message': 'auth_ref is required.'}, status=400)
            return True
        try:
            from backend.auth import resolve_auth_reference, _read_auth_payload
            import json as _json
            source_path = resolve_auth_reference(auth_ref)
            if not source_path or not source_path.exists():
                send_json(handler, {'ok': False, 'message': f'Auth file not found: {auth_ref}'}, status=404)
                return True
            payload = _read_auth_payload(source_path)
            if not isinstance(payload, dict):
                payload = {}
            if 'cloak' not in payload or not isinstance(payload.get('cloak'), dict):
                payload['cloak'] = {}
            payload['cloak']['mode'] = str(data.get('cloaking_mode') or 'auto').strip()
            payload['cloak']['strict_mode'] = bool(data.get('cloaking_strict_mode'))
            payload['cloak']['sensitive_words'] = list(data.get('cloaking_sensitive_words') or [])
            if 'cloaking_cache_user_id' in data:
                payload['cloak']['cache_user_id'] = bool(data['cloaking_cache_user_id'])
            if 'experimental_cch_signing' in data:
                payload['experimental_cch_signing'] = bool(data['experimental_cch_signing'])
            source_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = source_path.with_suffix(source_path.suffix + '.tmp')
            tmp.write_text(_json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(source_path)
            state = load_state()
            rebuild = rebuild_runtime_config_from_state(state)
            send_json(handler, {'ok': True, 'message': 'Cloaking config saved.', 'runtime_rebuilt': rebuild.get('rebuilt'), 'restart_required': True})
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to save cloaking config: {e}'}, status=500)
        return True
    if parsed.path == '/api/amp-config':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        item = data.get('item') if isinstance(data.get('item'), dict) else data
        try:
            state = load_state()
            amp_config = {
                'upstream_url': str(item.get('amp_upstream_url') or '').strip(),
                'restrict_localhost': bool(item.get('amp_restrict_localhost', True)),
                'force_mappings': bool(item.get('amp_force_model_mappings', False)),
                'model_mappings': [],
            }
            upstream_key = str(item.get('amp_upstream_api_key') or '').strip()
            if upstream_key:
                amp_config['upstream_api_key'] = upstream_key
            else:
                existing = (state.get('amp_config') or {})
                amp_config['upstream_api_key'] = existing.get('upstream_api_key', '') or ''
            mappings = item.get('amp_model_mappings')
            if isinstance(mappings, list):
                for m in mappings:
                    if isinstance(m, dict):
                        amp_config['model_mappings'].append({
                            'from': str(m.get('from') or '').strip(),
                            'to': str(m.get('to') or '').strip(),
                            'regex': bool(m.get('regex', False)),
                        })
            state['amp_config'] = amp_config
            save_state(state)
            rebuild = rebuild_runtime_config_from_state(state)
            send_json(handler, {'ok': True, 'message': 'AMP config saved.', 'runtime_rebuilt': rebuild.get('rebuilt'), 'restart_required': True})
        except ValueError as e:
            send_json(handler, {'ok': False, 'message': str(e)}, status=400)
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to save AMP config: {e}'}, status=500)
        return True
    if parsed.path == '/api/storage-config':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        item = data.get('item') if isinstance(data.get('item'), dict) else data
        try:
            from backend.proxy_env import save_proxy_env
            updates = {}
            env_map = {
                'pgstore_dsn': 'PGSTORE_DSN', 'pgstore_schema': 'PGSTORE_SCHEMA',
                'gitstore_git_url': 'GITSTORE_GIT_URL', 'gitstore_git_username': 'GITSTORE_GIT_USERNAME',
                'gitstore_git_token': 'GITSTORE_GIT_TOKEN', 'gitstore_git_branch': 'GITSTORE_GIT_BRANCH',
                'objectstore_endpoint': 'OBJECTSTORE_ENDPOINT', 'objectstore_access_key': 'OBJECTSTORE_ACCESS_KEY',
                'objectstore_secret_key': 'OBJECTSTORE_SECRET_KEY', 'objectstore_bucket': 'OBJECTSTORE_BUCKET',
            }
            for json_key, env_key in env_map.items():
                val = str(item.get(json_key) or '').strip()
                if val and val != '***':
                    updates[env_key] = val
            save_proxy_env(updates)
            send_json(handler, {'ok': True, 'message': 'Storage config saved. Restart proxy for changes to take effect.', 'restart_required': True})
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to save storage config: {e}'}, status=500)
        return True
    if parsed.path == '/api/home-config':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        item = data.get('item') if isinstance(data.get('item'), dict) else data
        try:
            from backend.proxy_env import save_proxy_env
            state = load_state()
            jwt_val = str(item.get('home_jwt') or '').strip()
            if jwt_val:
                save_proxy_env({'HOME_JWT': jwt_val})
            state['home_disable_cluster_discovery'] = bool(item.get('home_disable_cluster_discovery', False))
            save_state(state)
            send_json(handler, {'ok': True, 'message': 'Home config saved. Restart proxy for changes to take effect.', 'restart_required': True})
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to save home config: {e}'}, status=500)
        return True
    if parsed.path == '/api/vertex-import':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        content = str(data.get('content') or '').strip()
        if not content:
            send_json(handler, {'ok': False, 'message': 'File content is required.'}, status=400)
            return True
        try:
            prefix = str(data.get('prefix') or '').strip()
            from backend.tools import run_vertex_import
            result = run_vertex_import(content, prefix)
            send_json(handler, {'ok': True, 'message': result.get('message', 'Vertex SA key staged. Run the vertex-import tool to complete.')})
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed to stage Vertex key: {e}'}, status=500)
        return True
    if parsed.path == '/api/per-auth-cooling':
        if not isinstance(data, dict):
            send_json(handler, {'ok': False, 'message': 'Invalid payload.'}, status=400)
            return True
        action = str(data.get('action') or 'set_global').strip().lower()
        try:
            state = load_state()
            if action == 'set_global':
                state['disable_cooling'] = bool(data.get('disable_cooling', False))
                save_state(state)
                rebuild = rebuild_runtime_config_from_state(state)
                send_json(handler, {'ok': True, 'message': f'Global cooldown {"DISABLED" if state["disable_cooling"] else "ENABLED"}.', 'runtime_rebuilt': rebuild.get('rebuilt'), 'restart_required': True})
            elif action == 'set_per_auth':
                auth_ref = str(data.get('auth_ref') or '').strip()
                disable = bool(data.get('disable_cooling', False))
                if not auth_ref:
                    send_json(handler, {'ok': False, 'message': 'auth_ref is required.'}, status=400)
                    return True
                from backend.auth import resolve_auth_reference, _read_auth_payload
                import json as _json2
                source_path = resolve_auth_reference(auth_ref)
                if not source_path or not source_path.exists():
                    send_json(handler, {'ok': False, 'message': f'Auth file not found: {auth_ref}'}, status=404)
                    return True
                payload = _read_auth_payload(source_path)
                if not isinstance(payload, dict):
                    payload = {}
                payload['disable-cooling'] = disable
                source_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = source_path.with_suffix(source_path.suffix + '.tmp')
                tmp.write_text(_json2.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
                tmp.replace(source_path)
                rebuild = rebuild_runtime_config_from_state(state)
                send_json(handler, {'ok': True, 'message': f'Per-auth cooldown {"DISABLED" if disable else "ENABLED"} for {auth_ref}.', 'runtime_rebuilt': rebuild.get('rebuilt'), 'restart_required': True})
            else:
                send_json(handler, {'ok': False, 'message': f'Unknown action: {action}'}, status=400)
        except Exception as e:
            send_json(handler, {'ok': False, 'message': f'Failed: {e}'}, status=500)
        return True
    return False
