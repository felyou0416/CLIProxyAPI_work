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
from backend.request_metrics.cumulative import update_cumulative_stats


_OBSERVABILITY_CACHE_LOCK = threading.Lock()
_OBSERVABILITY_CACHE_COND = threading.Condition(_OBSERVABILITY_CACHE_LOCK)
_OBSERVABILITY_CACHE = {
    'ready': False,
    'refreshing': False,
    'refreshed_at': 0.0,
    'generation': 0,
    'events': [],
    'clients': [],
    'auth_health': [],
}
_OBSERVABILITY_REFRESH_INTERVAL_SECONDS = 15.0
_OBSERVABILITY_EVENT_LIMIT = 300
_OBSERVABILITY_SUMMARY_LIMIT = 200
_OBSERVABILITY_REFRESH_WAIT_SECONDS = 45.0


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

    # 增量更新累积 Token 统计
    if events:
        try:
            update_cumulative_stats(events)
        except Exception:
            pass

    # 各汇总步骤独立 try/except，避免一个失败级联阻断其他汇总
    try:
        clients = summarize_clients(events)[:summary_limit]
    except Exception:
        clients = []

    try:
        auth_health = summarize_auth_health(auth_items, events, provider_models, runtime_test_state)[:summary_limit]
    except Exception:
        auth_health = []

    return {
        'events': events,
        'clients': clients,
        'auth_health': auth_health,
        'refreshed_at': time.time(),
    }


def _cache_view() -> dict:
    return {
        'ready': bool(_OBSERVABILITY_CACHE.get('ready')),
        'refreshing': bool(_OBSERVABILITY_CACHE.get('refreshing')),
        'refreshed_at': float(_OBSERVABILITY_CACHE.get('refreshed_at') or 0.0),
        'generation': int(_OBSERVABILITY_CACHE.get('generation') or 0),
        'events': list(_OBSERVABILITY_CACHE.get('events') or []),
        'clients': list(_OBSERVABILITY_CACHE.get('clients') or []),
        'auth_health': list(_OBSERVABILITY_CACHE.get('auth_health') or []),
    }


def _wait_for_refresh_unlock(started_generation: int) -> dict:
    deadline = time.time() + _OBSERVABILITY_REFRESH_WAIT_SECONDS
    with _OBSERVABILITY_CACHE_COND:
        while _OBSERVABILITY_CACHE.get('refreshing'):
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            _OBSERVABILITY_CACHE_COND.wait(timeout=remaining)
            if int(_OBSERVABILITY_CACHE.get('generation') or 0) > started_generation:
                break
        return _cache_view()


def refresh_observability_cache(force: bool = False) -> dict:
    """Rebuild the observability cache.

    Concurrent callers no longer receive a stale snapshot mid-refresh.
    Background refresh waits for the in-flight rebuild; forced refresh waits
    for it and then rebuilds once more so the button always re-reads logs.
    """
    with _OBSERVABILITY_CACHE_COND:
        started_generation = int(_OBSERVABILITY_CACHE.get('generation') or 0)
        if _OBSERVABILITY_CACHE.get('refreshing'):
            should_run = False
        else:
            _OBSERVABILITY_CACHE['refreshing'] = True
            should_run = True

    if not should_run:
        waited = _wait_for_refresh_unlock(started_generation)
        if not force:
            return waited
        with _OBSERVABILITY_CACHE_COND:
            if _OBSERVABILITY_CACHE.get('refreshing'):
                return _cache_view()
            _OBSERVABILITY_CACHE['refreshing'] = True

    try:
        snapshot = build_observability_snapshot()
        with _OBSERVABILITY_CACHE_COND:
            _OBSERVABILITY_CACHE['events'] = snapshot.get('events') or []
            _OBSERVABILITY_CACHE['clients'] = snapshot.get('clients') or []
            _OBSERVABILITY_CACHE['auth_health'] = snapshot.get('auth_health') or []
            _OBSERVABILITY_CACHE['refreshed_at'] = float(snapshot.get('refreshed_at') or time.time())
            _OBSERVABILITY_CACHE['ready'] = True
            _OBSERVABILITY_CACHE['generation'] = int(_OBSERVABILITY_CACHE.get('generation') or 0) + 1
            _OBSERVABILITY_CACHE['refreshing'] = False
            _OBSERVABILITY_CACHE_COND.notify_all()
            return _cache_view()
    except Exception:
        with _OBSERVABILITY_CACHE_COND:
            _OBSERVABILITY_CACHE['refreshing'] = False
            _OBSERVABILITY_CACHE_COND.notify_all()
            return _cache_view()


def get_observability_cache() -> dict:
    with _OBSERVABILITY_CACHE_LOCK:
        return _cache_view()


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
