import threading
import time

from backend.auth import list_auth_files, get_configured_provider_models
from backend.tools import get_provider_model_test_state
from backend.paths import PROXY_STDOUT, REQUEST_ARCHIVE_DIR
from backend.request_metrics.parsing import (
    parse_error_logs,
    parse_precise_request_events,
    parse_proxy_requests,
    prune_request_logs,
    _request_log_dirs,
)
from backend.request_metrics.merge import merge_request_events
from backend.request_metrics.summary import summarize_auth_health, summarize_clients
from backend.request_metrics.cumulative import update_cumulative_stats
from backend.request_monitoring_config import load_request_monitoring_config, request_monitoring_enabled


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

# The table cache is deliberately separate from the lightweight observability
# cache. Request pagination needs one complete, stable ordering; summaries only
# need a small recent sample and refresh much more often.
_REQUEST_EVENTS_CACHE_LOCK = threading.Lock()
_REQUEST_EVENTS_CACHE_COND = threading.Condition(_REQUEST_EVENTS_CACHE_LOCK)
_REQUEST_EVENTS_CACHE = {
    'ready': False,
    'refreshing': False,
    'refreshed_at': 0.0,
    'generation': 0,
    'expires_at': 0.0,
    'source_signatures': None,
    'events': [],
}
_REQUEST_EVENTS_CACHE_WAIT_SECONDS = 90.0


def _request_log_source_signatures() -> tuple[tuple[str, int, int], ...]:
    """Return signatures for every file consumed by the request-event parsers."""
    paths = {}
    for log_dir in _request_log_dirs():
        try:
            if not log_dir.is_dir():
                continue
            for path in log_dir.glob('*.log'):
                if path.is_file():
                    paths[str(path)] = path
        except Exception:
            continue

    for path in (PROXY_STDOUT,):
        try:
            if path.is_file():
                paths[str(path)] = path
        except Exception:
            continue

    try:
        if REQUEST_ARCHIVE_DIR.is_dir():
            for path in REQUEST_ARCHIVE_DIR.glob('request-events-*.jsonl'):
                if path.is_file():
                    paths[str(path)] = path
    except Exception:
        pass

    signatures = []
    for key, path in paths.items():
        try:
            stat = path.stat()
            signatures.append((key, int(stat.st_mtime_ns), int(stat.st_size)))
        except Exception:
            continue
    signatures.sort(key=lambda item: item[0])
    return tuple(signatures)


# Fallback constants document the runtime defaults; state.json values are read
# through load_request_monitoring_config at each refresh cycle.
_OBSERVABILITY_REFRESH_INTERVAL_SECONDS = 15.0
# 这个值决定后台观测缓存每次刷新要解析多少个精细日志文件（每个约1-2MB）。
# 这个缓存只用于“客户端汇总/Auth健康度/累计Token统计”这几个画像型统计，
# 不是表格展示（表格分页已经改成按需懒加载，见 get_precise_request_events_page），
# 不需要看很多历史样本——近期一个窗口的画像已经够用，长期累积数据由
# update_cumulative_stats 单独维护。之前设为 300 时，这个后台线程每 15 秒
# 就要解析大量文件，持续占用 CPU/磁盘 I/O，会拖慢同进程里其他请求的响应
# （包括"重启代理服务"这类需要快速返回的操作），所以调低到一个更轻量的值。
_OBSERVABILITY_EVENT_LIMIT = 100
_OBSERVABILITY_SUMMARY_LIMIT = 200
_OBSERVABILITY_REFRESH_WAIT_SECONDS = 45.0


def build_observability_snapshot(event_limit: int = _OBSERVABILITY_EVENT_LIMIT, summary_limit: int = _OBSERVABILITY_SUMMARY_LIMIT) -> dict:
    if not request_monitoring_enabled():
        return {
            'events': [],
            'clients': [],
            'auth_health': [],
            'refreshed_at': time.time(),
            'disabled': True,
        }
    # 注意：prune_request_logs() 必须在 parse_precise_request_events() 之后调用.
    # 原因：prune 会将超出 50 个上限的旧 .log 文件归档后删除；
    # 若先 prune 再 parse，被清理的文件就无法被当次刷新读到，
    # 导致高频请求时精细日志事件与 proxy 事件无法对齐（出现大量"未匹配详情"）。
    # 正确顺序：先读完所有文件，再清理旧文件。
    provider_models = get_configured_provider_models()
    events = merge_request_events(
        parse_proxy_requests(limit=event_limit),
        parse_precise_request_events(limit=event_limit),
        parse_error_logs(limit=event_limit),
        provider_models,
    )
    prune_request_logs()
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
    enabled = request_monitoring_enabled()
    return {
        'ready': bool(_OBSERVABILITY_CACHE.get('ready')) and enabled,
        'refreshing': bool(_OBSERVABILITY_CACHE.get('refreshing')) and enabled,
        'refreshed_at': float(_OBSERVABILITY_CACHE.get('refreshed_at') or 0.0),
        'generation': int(_OBSERVABILITY_CACHE.get('generation') or 0),
        'events': list(_OBSERVABILITY_CACHE.get('events') or []) if enabled else [],
        'clients': list(_OBSERVABILITY_CACHE.get('clients') or []) if enabled else [],
        'auth_health': list(_OBSERVABILITY_CACHE.get('auth_health') or []) if enabled else [],
        'monitoring_enabled': enabled,
        'disabled': not enabled,
    }


def _clear_observability_cache() -> None:
    with _OBSERVABILITY_CACHE_COND:
        _OBSERVABILITY_CACHE['ready'] = True
        _OBSERVABILITY_CACHE['refreshing'] = False
        _OBSERVABILITY_CACHE['refreshed_at'] = time.time()
        _OBSERVABILITY_CACHE['events'] = []
        _OBSERVABILITY_CACHE['clients'] = []
        _OBSERVABILITY_CACHE['auth_health'] = []
        _OBSERVABILITY_CACHE_COND.notify_all()


def _clear_request_events_cache() -> dict:
    with _REQUEST_EVENTS_CACHE_COND:
        _REQUEST_EVENTS_CACHE['ready'] = True
        _REQUEST_EVENTS_CACHE['refreshing'] = False
        _REQUEST_EVENTS_CACHE['refreshed_at'] = time.time()
        _REQUEST_EVENTS_CACHE['expires_at'] = 0.0
        _REQUEST_EVENTS_CACHE['source_signatures'] = _request_log_source_signatures()
        _REQUEST_EVENTS_CACHE['events'] = []
        _REQUEST_EVENTS_CACHE_COND.notify_all()
        return _request_events_cache_view()


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
    if not request_monitoring_enabled():
        _clear_observability_cache()
        return get_observability_cache()
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
    if not request_monitoring_enabled():
        _clear_observability_cache()
    with _OBSERVABILITY_CACHE_LOCK:
        return _cache_view()


def _request_events_cache_view() -> dict:
    enabled = request_monitoring_enabled()
    return {
        'ready': bool(_REQUEST_EVENTS_CACHE.get('ready')) and enabled,
        'refreshing': bool(_REQUEST_EVENTS_CACHE.get('refreshing')) and enabled,
        'refreshed_at': float(_REQUEST_EVENTS_CACHE.get('refreshed_at') or 0.0),
        'generation': int(_REQUEST_EVENTS_CACHE.get('generation') or 0),
        'events': list(_REQUEST_EVENTS_CACHE.get('events') or []) if enabled else [],
        'monitoring_enabled': enabled,
        'disabled': not enabled,
    }


def _rebuild_request_events_cache(start_signatures=None) -> dict:
    if not request_monitoring_enabled():
        return _clear_request_events_cache()
    config = load_request_monitoring_config()
    if start_signatures is None:
        start_signatures = _request_log_source_signatures()
    try:
        events = merge_request_events(
            # proxy.stdout.log is append-only and can span months. It only
            # fills the short interval before a detailed request log exists;
            # retaining the recent window prevents it from becoming a second,
            # unbounded history source.
            parse_proxy_requests(limit=300),
            parse_precise_request_events(limit=0),
            parse_error_logs(limit=300),
            get_configured_provider_models(),
        )
        # request_id is the stable source identity. Keep a fallback key for
        # legacy events that predate request IDs.
        seen = set()
        unique_events = []
        for event in events:
            key = str(event.get('request_id') or '').strip()
            if not key:
                key = '|'.join([
                    str(event.get('timestamp') or ''),
                    str(event.get('path') or ''),
                    str(event.get('status_code') or ''),
                    str(event.get('source') or ''),
                ])
            if key in seen:
                continue
            seen.add(key)
            unique_events.append(event)
        unique_events.sort(
            key=lambda item: (
                -int(item.get('timestamp') or 0),
                str(item.get('request_id') or ''),
                str(item.get('log_file') or ''),
            ),
        )
        now = time.time()
        with _REQUEST_EVENTS_CACHE_COND:
            _REQUEST_EVENTS_CACHE['events'] = unique_events
            _REQUEST_EVENTS_CACHE['refreshed_at'] = now
            if not request_monitoring_enabled():
                _REQUEST_EVENTS_CACHE['events'] = []
            _REQUEST_EVENTS_CACHE['expires_at'] = now + config['request_events_cache_ttl_seconds']
            _REQUEST_EVENTS_CACHE['source_signatures'] = start_signatures
            _REQUEST_EVENTS_CACHE['ready'] = True
            _REQUEST_EVENTS_CACHE['generation'] = int(_REQUEST_EVENTS_CACHE.get('generation') or 0) + 1
            _REQUEST_EVENTS_CACHE['refreshing'] = False
            _REQUEST_EVENTS_CACHE_COND.notify_all()
            return _request_events_cache_view()
    except Exception:
        with _REQUEST_EVENTS_CACHE_COND:
            _REQUEST_EVENTS_CACHE['refreshing'] = False
            _REQUEST_EVENTS_CACHE_COND.notify_all()
            return _request_events_cache_view()


def _has_new_request_logs(refreshed_at: float, source_signatures=None) -> bool:
    """Check whether a consumed request-log file was created, changed, or removed."""
    if refreshed_at <= 0:
        return True
    previous = source_signatures
    if previous is None:
        previous = _REQUEST_EVENTS_CACHE.get('source_signatures')
    if previous is None:
        return True
    return _request_log_source_signatures() != tuple(previous)


def get_request_events_cache(force: bool = False, wait: bool = True) -> dict:
    """Return a stable request-event snapshot, rebuilding in the background when requested."""
    if not request_monitoring_enabled():
        return _clear_request_events_cache()
    with _REQUEST_EVENTS_CACHE_COND:
        now = time.time()
        refreshed_at = float(_REQUEST_EVENTS_CACHE.get('refreshed_at') or 0.0)
        has_new_logs = _has_new_request_logs(refreshed_at)
        fresh = (
            _REQUEST_EVENTS_CACHE.get('ready')
            and now < float(_REQUEST_EVENTS_CACHE.get('expires_at') or 0.0)
            and not has_new_logs
        )
        if not force and fresh:
            return _request_events_cache_view()
        if _REQUEST_EVENTS_CACHE.get('refreshing'):
            if not wait:
                return _request_events_cache_view()
            deadline = now + _REQUEST_EVENTS_CACHE_WAIT_SECONDS
            while _REQUEST_EVENTS_CACHE.get('refreshing'):
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                _REQUEST_EVENTS_CACHE_COND.wait(timeout=remaining)
            return _request_events_cache_view()
        _REQUEST_EVENTS_CACHE['refreshing'] = True
        rebuild_signatures = _request_log_source_signatures()

    if not wait:
        threading.Thread(
            target=_rebuild_request_events_cache,
            args=(rebuild_signatures,),
            name='dashboard-request-events-cache',
            daemon=True,
        ).start()
        return _request_events_cache_view()
    return _rebuild_request_events_cache(rebuild_signatures)


def ensure_observability_cache() -> dict:
    cache = get_observability_cache()
    if cache.get('ready') or cache.get('disabled'):
        return cache
    return refresh_observability_cache()


def start_observability_refresh_thread(interval_seconds: float | None = None) -> threading.Thread:
    """
    启动后台观测缓存刷新线程。

    重要：这里不在调用方（server.py 的 main()）所在的主线程里同步做首次刷新。
    server.py 的注释明确写着“Accept HTTP immediately so launcher health checks
    and the UI do not wait”，但改动前的实现是 refresh_observability_cache()
    直接在 start_observability_refresh_thread() 里同步执行，而 main() 又是在
    server.serve_forever() 之前调用它——也就是说 HTTP 端口在首次全量日志解析
    完成之前根本不会开始监听。当保留的日志文件数较多时（比如提高
    _REQUEST_LOG_KEEP_FILES 之后），首次解析要几十秒，Dashboard 启动 /
    重启期间这段时间整个进程对外都是不可访问的，跟注释里"立刻接受请求"的
    设计意图正好相反。
    这里把首次刷新也放进后台线程执行，服务器可以立刻开始监听端口；缓存在
    刷新完成前，前端请求会走 ensure_observability_cache() 的等待/重试逻辑，
    而不是让整个进程卡住无法响应任何请求（包括健康检查）。
    """
    def _worker():
        while True:
            config = load_request_monitoring_config()
            if config['request_monitoring_enabled']:
                refresh_observability_cache()
                # Build the heavier, pagination-specific snapshot independently.
                # The cache checks source signatures and performs any rebuild in the background.
                get_request_events_cache(wait=False)
            else:
                _clear_observability_cache()
                _clear_request_events_cache()
            sleep_seconds = interval_seconds if interval_seconds is not None else config['request_observability_refresh_seconds']
            time.sleep(max(1.0, float(sleep_seconds)))

    thread = threading.Thread(target=_worker, name='dashboard-observability-cache', daemon=True)
    thread.start()
    return thread
