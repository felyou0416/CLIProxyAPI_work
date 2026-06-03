import threading
import time

from backend.auth import list_auth_files, get_configured_provider_models
from backend.tools import get_provider_model_test_state
from backend.request_metrics.parsing import (
    parse_error_logs,
    parse_precise_request_events,
    parse_proxy_requests,
    prune_request_logs,
)
from backend.request_metrics.merge import merge_request_events
from backend.request_metrics.summary import summarize_auth_health, summarize_clients


_OBSERVABILITY_CACHE_LOCK = threading.Lock()
_OBSERVABILITY_CACHE = {
    'ready': False,
    'refreshing': False,
    'refreshed_at': 0.0,
    'events': [],
    'clients': [],
    'auth_health': [],
}
_OBSERVABILITY_REFRESH_INTERVAL_SECONDS = 15.0
_OBSERVABILITY_EVENT_LIMIT = 300
_OBSERVABILITY_SUMMARY_LIMIT = 200


def build_observability_snapshot(event_limit: int = _OBSERVABILITY_EVENT_LIMIT, summary_limit: int = _OBSERVABILITY_SUMMARY_LIMIT) -> dict:
    prune_request_logs()
    provider_models = get_configured_provider_models()
    events = merge_request_events(
        parse_proxy_requests(limit=event_limit),
        parse_precise_request_events(limit=event_limit),
        parse_error_logs(limit=event_limit),
        provider_models,
    )
    auth_items = list_auth_files()
    runtime_test_state = get_provider_model_test_state()
    return {
        'events': events,
        'clients': summarize_clients(events)[:summary_limit],
        'auth_health': summarize_auth_health(auth_items, events, provider_models, runtime_test_state)[:summary_limit],
        'refreshed_at': time.time(),
    }


def refresh_observability_cache() -> dict:
    with _OBSERVABILITY_CACHE_LOCK:
        if _OBSERVABILITY_CACHE.get('refreshing'):
            return dict(_OBSERVABILITY_CACHE)
        _OBSERVABILITY_CACHE['refreshing'] = True
    try:
        snapshot = build_observability_snapshot()
        with _OBSERVABILITY_CACHE_LOCK:
            _OBSERVABILITY_CACHE['events'] = snapshot.get('events') or []
            _OBSERVABILITY_CACHE['clients'] = snapshot.get('clients') or []
            _OBSERVABILITY_CACHE['auth_health'] = snapshot.get('auth_health') or []
            _OBSERVABILITY_CACHE['refreshed_at'] = float(snapshot.get('refreshed_at') or time.time())
            _OBSERVABILITY_CACHE['ready'] = True
            _OBSERVABILITY_CACHE['refreshing'] = False
            return dict(_OBSERVABILITY_CACHE)
    except Exception:
        with _OBSERVABILITY_CACHE_LOCK:
            _OBSERVABILITY_CACHE['refreshing'] = False
            return dict(_OBSERVABILITY_CACHE)


def get_observability_cache() -> dict:
    with _OBSERVABILITY_CACHE_LOCK:
        return {
            'ready': bool(_OBSERVABILITY_CACHE.get('ready')),
            'refreshing': bool(_OBSERVABILITY_CACHE.get('refreshing')),
            'refreshed_at': float(_OBSERVABILITY_CACHE.get('refreshed_at') or 0.0),
            'events': list(_OBSERVABILITY_CACHE.get('events') or []),
            'clients': list(_OBSERVABILITY_CACHE.get('clients') or []),
            'auth_health': list(_OBSERVABILITY_CACHE.get('auth_health') or []),
        }


def ensure_observability_cache() -> dict:
    cache = get_observability_cache()
    if cache.get('ready'):
        return cache
    return refresh_observability_cache()


def start_observability_refresh_thread(interval_seconds: float = _OBSERVABILITY_REFRESH_INTERVAL_SECONDS) -> threading.Thread:
    refresh_observability_cache()

    def _worker():
        while True:
            time.sleep(max(1.0, float(interval_seconds or _OBSERVABILITY_REFRESH_INTERVAL_SECONDS)))
            refresh_observability_cache()

    thread = threading.Thread(target=_worker, name='dashboard-observability-cache', daemon=True)
    thread.start()
    return thread
