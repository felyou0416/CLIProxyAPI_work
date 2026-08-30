"""累积 Token 统计存储。

按 模型 / 客户端 / Provider / 日期 / 小时 维度增量累积 token 使用量。
基于事件 timestamp 去重，仅处理上次刷新之后的新事件。
持久化到 STORAGE_DIR / cumulative_token_stats.json。
"""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from backend.paths import STORAGE_DIR
from backend.request_metrics.summary import _get_default_api_key_masked

# 延迟导入，避免启动时循环依赖
def _merge_all_events(limit: int = 5000) -> list[dict]:
    """合并 proxy stdout、精确请求日志、错误日志以及归档事件。"""
    from backend.request_metrics.parsing import (
        parse_error_logs,
        parse_precise_request_events,
        parse_proxy_requests,
    )
    from backend.request_metrics.merge import merge_request_events
    from backend.auth import get_configured_aggregate_models

    provider_models = get_configured_aggregate_models()
    return merge_request_events(
        parse_proxy_requests(limit=limit),
        parse_precise_request_events(limit=limit),
        parse_error_logs(limit=limit),
        provider_models,
    )

_CUMULATIVE_FILE = STORAGE_DIR / 'cumulative_token_stats.json'
_CUMULATIVE_LOCK = threading.Lock()

# 每日数据保留天数（超过自动滚动为月度汇总）
_DAILY_RETENTION_DAYS = 90


def _default_stats() -> dict:
    return {
        'version': 5,
        'updated_at': 0,
        'last_event_ts': 0,
        'totals': {
            'request_count': 0,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total_tokens': 0,
        },
        'by_model': {},
        'by_client': {},
        'by_provider': {},
        'daily': {},
        'hourly': {},
    }


def _entry_default() -> dict:
    return {
        'request_count': 0,
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'total_tokens': 0,
    }


def _safe_int(value, default=0) -> int:
    """安全地将值转为 int，失败时返回 default。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _add_to_entry(entry: dict, event: dict) -> None:
    entry['request_count'] = int(entry.get('request_count', 0)) + 1
    entry['prompt_tokens'] = int(entry.get('prompt_tokens', 0)) + _safe_int(event.get('prompt_tokens'))
    entry['completion_tokens'] = int(entry.get('completion_tokens', 0)) + _safe_int(event.get('completion_tokens'))
    entry['total_tokens'] = int(entry.get('total_tokens', 0)) + _safe_int(event.get('total_tokens'))


def _add_event_to_stats(stats: dict, event: dict, ts: int) -> None:
    """将单个请求事件记录到 totals、by_model、by_client、by_provider、daily 及 hourly。"""
    # ---- 总计 ----
    _add_to_entry(stats['totals'], event)

    # ---- 按模型 ----
    model = str(event.get('requested_model') or '').strip() or 'unknown'
    _add_to_entry(stats['by_model'].setdefault(model, _entry_default()), event)

    # ---- 模型背后实际 upstream 分布 ----
    actual = str(event.get('actual_model') or event.get('routed_model') or '').strip()
    if actual and actual != model:
        model_entry = stats['by_model'][model]
        if 'actual_model_distribution' not in model_entry:
            model_entry['actual_model_distribution'] = {}
        sub = model_entry['actual_model_distribution'].setdefault(actual, _entry_default())
        _add_to_entry(sub, event)

    # ---- 按客户端 (API Key) ----
    client = str(event.get('api_key_masked') or '').strip() or _get_default_api_key_masked()
    _add_to_entry(stats['by_client'].setdefault(client, _entry_default()), event)

    # ---- 按 Provider ----
    provider = str(event.get('inferred_provider') or event.get('actual_provider') or '').strip() or 'unknown'
    _add_to_entry(stats['by_provider'].setdefault(provider, _entry_default()), event)

    # ---- 按日期 ----
    try:
        key_date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
    except Exception:
        key_date = datetime.now().strftime('%Y-%m-%d')
    daily = stats['daily'].setdefault(key_date, _entry_default())
    _add_to_entry(daily, event)

    # 每日细分: by_model
    daily_by_model = daily.setdefault('by_model', {})
    _add_to_entry(daily_by_model.setdefault(model, _entry_default()), event)
    if actual and actual != model:
        d_model_entry = daily_by_model[model]
        if 'actual_model_distribution' not in d_model_entry:
            d_model_entry['actual_model_distribution'] = {}
        d_sub = d_model_entry['actual_model_distribution'].setdefault(actual, _entry_default())
        _add_to_entry(d_sub, event)

    # 每日细分: by_client & by_provider
    daily_by_client = daily.setdefault('by_client', {})
    _add_to_entry(daily_by_client.setdefault(client, _entry_default()), event)
    daily_by_provider = daily.setdefault('by_provider', {})
    _add_to_entry(daily_by_provider.setdefault(provider, _entry_default()), event)

    # ---- 按小时 ----
    try:
        key_hour = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:00')
    except Exception:
        key_hour = datetime.now().strftime('%Y-%m-%d %H:00')
    hourly = stats.setdefault('hourly', {}).setdefault(key_hour, _entry_default())
    _add_to_entry(hourly, event)

    # 每小时细分: by_model
    hourly_by_model = hourly.setdefault('by_model', {})
    _add_to_entry(hourly_by_model.setdefault(model, _entry_default()), event)
    if actual and actual != model:
        h_model_entry = hourly_by_model[model]
        if 'actual_model_distribution' not in h_model_entry:
            h_model_entry['actual_model_distribution'] = {}
        h_sub = h_model_entry['actual_model_distribution'].setdefault(actual, _entry_default())
        _add_to_entry(h_sub, event)

    hourly_by_client = hourly.setdefault('by_client', {})
    _add_to_entry(hourly_by_client.setdefault(client, _entry_default()), event)
    hourly_by_provider = hourly.setdefault('by_provider', {})
    _add_to_entry(hourly_by_provider.setdefault(provider, _entry_default()), event)


def _rebuild_stats_internal(stats: dict, events: list[dict]) -> dict:
    """内部使用的锁无关重建函数，用于避免迁移或全量重建时死锁。"""
    stats['totals'] = {
        'request_count': 0,
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'total_tokens': 0,
    }
    stats['by_model'] = {}
    stats['by_client'] = {}
    stats['by_provider'] = {}
    stats['daily'] = {}
    stats['hourly'] = {}

    max_ts = 0
    for event in events:
        ts = int(event.get('timestamp') or 0)
        if ts > max_ts:
            max_ts = ts
        _add_event_to_stats(stats, event, ts)

    # ---- 清理超过保留期的每日数据 ----
    cutoff = datetime.now().strftime('%Y-%m-%d')
    try:
        cutoff_ts = time.time() - _DAILY_RETENTION_DAYS * 86400
        cutoff = datetime.fromtimestamp(cutoff_ts).strftime('%Y-%m-%d')
    except Exception:
        pass
    stale_dates = [d for d in stats.get('daily', {}) if d < cutoff]
    for d in stale_dates:
        del stats['daily'][d]

    # ---- 清理超过保留期的每小时数据 (保留48小时) ----
    try:
        cutoff_hour_ts = time.time() - 48 * 3600
        cutoff_hour = datetime.fromtimestamp(cutoff_hour_ts).strftime('%Y-%m-%d %H:00')
    except Exception:
        cutoff_hour = datetime.now().strftime('%Y-%m-%d %H:00')
    stale_hours = [h for h in stats.get('hourly', {}) if h < cutoff_hour]
    for h in stale_hours:
        del stats['hourly'][h]

    stats['last_event_ts'] = max_ts
    stats['updated_at'] = int(time.time())
    return stats


def _backfill_daily_breakdowns(stats: dict) -> bool:
    """从 request_archive 的 JSONL 归档中快速回填历史天数的 by_model / by_client / by_provider 细分数据。"""
    from backend.paths import REQUEST_ARCHIVE_DIR
    if not REQUEST_ARCHIVE_DIR.exists():
        return False

    modified = False
    daily = stats.setdefault('daily', {})

    for archive_file in sorted(REQUEST_ARCHIVE_DIR.glob('request-events-*.jsonl')):
        try:
            with open(archive_file, 'r', encoding='utf-8', errors='ignore') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    event = json.loads(line)
                    ts = int(event.get('timestamp') or 0)
                    try:
                        date_key = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                    except Exception:
                        continue

                    # 回填单日 daily
                    day_entry = daily.setdefault(date_key, _entry_default())

                    daily_by_model = day_entry.setdefault('by_model', {})
                    model = str(event.get('requested_model') or '').strip() or 'unknown'
                    _add_to_entry(daily_by_model.setdefault(model, _entry_default()), event)

                    actual = str(event.get('actual_model') or event.get('routed_model') or '').strip()
                    if actual and actual != model:
                        d_model_entry = daily_by_model[model]
                        if 'actual_model_distribution' not in d_model_entry:
                            d_model_entry['actual_model_distribution'] = {}
                        d_sub = d_model_entry['actual_model_distribution'].setdefault(actual, _entry_default())
                        _add_to_entry(d_sub, event)

                    daily_by_client = day_entry.setdefault('by_client', {})
                    client = str(event.get('api_key_masked') or '').strip() or _get_default_api_key_masked()
                    _add_to_entry(daily_by_client.setdefault(client, _entry_default()), event)

                    daily_by_provider = day_entry.setdefault('by_provider', {})
                    provider = str(event.get('inferred_provider') or event.get('actual_provider') or '').strip() or 'unknown'
                    _add_to_entry(daily_by_provider.setdefault(provider, _entry_default()), event)
                    modified = True
        except Exception:
            continue

    # 对所有天数，确保 top-level 计数与 by_model 的总和保持一致
    for d, day_data in daily.items():
        by_m = day_data.get('by_model', {})
        if by_m:
            sum_req = sum(v.get('request_count', 0) for v in by_m.values())
            sum_tokens = sum(v.get('total_tokens', 0) for v in by_m.values())
            sum_prompt = sum(v.get('prompt_tokens', 0) for v in by_m.values())
            sum_comp = sum(v.get('completion_tokens', 0) for v in by_m.values())
            if sum_req > day_data.get('request_count', 0):
                day_data['request_count'] = sum_req
            if sum_tokens > day_data.get('total_tokens', 0):
                day_data['total_tokens'] = sum_tokens
                day_data['prompt_tokens'] = sum_prompt
                day_data['completion_tokens'] = sum_comp

    return modified


def _load_stats() -> dict:
    try:
        if _CUMULATIVE_FILE.exists():
            content = _CUMULATIVE_FILE.read_text(encoding='utf-8')
            stats = json.loads(content)
            if isinstance(stats, dict):
                version = stats.get('version')
                if version == 5:
                    return stats
                # Schema migrations must preserve durable totals.
                stats['version'] = 5
                stats.setdefault('hourly', {})
                _backfill_daily_breakdowns(stats)
                _save_stats(stats)
                return stats
    except Exception:
        pass
    return _default_stats()


def _save_stats(stats: dict) -> None:
    _CUMULATIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(_CUMULATIVE_FILE) + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(stats, fh, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, str(_CUMULATIVE_FILE))
    except Exception:
        pass


def update_cumulative_stats(events: list[dict]) -> dict | None:
    """增量更新累积统计。返回更新后的 stats，无新事件时返回 None。"""
    if not events:
        return None

    with _CUMULATIVE_LOCK:
        stats = _load_stats()
        last_ts = int(stats.get('last_event_ts', 0))
        max_ts = last_ts

        new_count = 0
        for event in events:
            ts = int(event.get('timestamp') or 0)
            if ts <= last_ts:
                continue
            new_count += 1
            if ts > max_ts:
                max_ts = ts
            _add_event_to_stats(stats, event, ts)

        if new_count == 0:
            return None

        # ---- 清理超过保留期的每日数据 ----
        cutoff = datetime.now().strftime('%Y-%m-%d')
        try:
            cutoff_ts = time.time() - _DAILY_RETENTION_DAYS * 86400
            cutoff = datetime.fromtimestamp(cutoff_ts).strftime('%Y-%m-%d')
        except Exception:
            pass
        stale_dates = [d for d in stats.get('daily', {}) if d < cutoff]
        for d in stale_dates:
            del stats['daily'][d]

        # ---- 清理超过保留期的每小时数据 (保留48小时) ----
        try:
            cutoff_hour_ts = time.time() - 48 * 3600
            cutoff_hour = datetime.fromtimestamp(cutoff_hour_ts).strftime('%Y-%m-%d %H:00')
        except Exception:
            cutoff_hour = datetime.now().strftime('%Y-%m-%d %H:00')
        stale_hours = [h for h in stats.setdefault('hourly', {}).keys() if h < cutoff_hour]
        for h in stale_hours:
            del stats['hourly'][h]

        stats['last_event_ts'] = max_ts
        stats['updated_at'] = int(time.time())

        _save_stats(stats)
        return stats


def get_cumulative_stats() -> dict:
    """返回当前累积统计快照，附带按 token 排序的模型/客户端/Provider 排行。"""
    with _CUMULATIVE_LOCK:
        stats = _load_stats()

        # 全局模型聚合：从 daily 汇总计算更准确的各模型总量与调用次数
        all_models = {}
        for day_entry in stats.get('daily', {}).values():
            for m, m_data in day_entry.get('by_model', {}).items():
                cur = all_models.setdefault(m, _entry_default())
                cur['request_count'] += m_data.get('request_count', 0)
                cur['prompt_tokens'] += m_data.get('prompt_tokens', 0)
                cur['completion_tokens'] += m_data.get('completion_tokens', 0)
                cur['total_tokens'] += m_data.get('total_tokens', 0)
                if 'actual_model_distribution' in m_data:
                    dist = cur.setdefault('actual_model_distribution', {})
                    for act_m, act_data in m_data['actual_model_distribution'].items():
                        act_cur = dist.setdefault(act_m, _entry_default())
                        act_cur['request_count'] += act_data.get('request_count', 0)
                        act_cur['prompt_tokens'] += act_data.get('prompt_tokens', 0)
                        act_cur['completion_tokens'] += act_data.get('completion_tokens', 0)
                        act_cur['total_tokens'] += act_data.get('total_tokens', 0)

        for m, m_data in stats.get('by_model', {}).items():
            cur = all_models.setdefault(m, _entry_default())
            if m_data.get('total_tokens', 0) > cur.get('total_tokens', 0):
                cur['total_tokens'] = m_data.get('total_tokens', 0)
                cur['prompt_tokens'] = m_data.get('prompt_tokens', 0)
                cur['completion_tokens'] = m_data.get('completion_tokens', 0)
            if m_data.get('request_count', 0) > cur.get('request_count', 0):
                cur['request_count'] = m_data.get('request_count', 0)

        all_clients = {}
        for day_entry in stats.get('daily', {}).values():
            for c, c_data in day_entry.get('by_client', {}).items():
                cur = all_clients.setdefault(c, _entry_default())
                cur['request_count'] += c_data.get('request_count', 0)
                cur['prompt_tokens'] += c_data.get('prompt_tokens', 0)
                cur['completion_tokens'] += c_data.get('completion_tokens', 0)
                cur['total_tokens'] += c_data.get('total_tokens', 0)
        for c, c_data in stats.get('by_client', {}).items():
            cur = all_clients.setdefault(c, _entry_default())
            if c_data.get('total_tokens', 0) > cur.get('total_tokens', 0):
                cur['total_tokens'] = c_data.get('total_tokens', 0)
                cur['prompt_tokens'] = c_data.get('prompt_tokens', 0)
                cur['completion_tokens'] = c_data.get('completion_tokens', 0)
            if c_data.get('request_count', 0) > cur.get('request_count', 0):
                cur['request_count'] = c_data.get('request_count', 0)

        all_providers = {}
        for day_entry in stats.get('daily', {}).values():
            for p, p_data in day_entry.get('by_provider', {}).items():
                cur = all_providers.setdefault(p, _entry_default())
                cur['request_count'] += p_data.get('request_count', 0)
                cur['prompt_tokens'] += p_data.get('prompt_tokens', 0)
                cur['completion_tokens'] += p_data.get('completion_tokens', 0)
                cur['total_tokens'] += p_data.get('total_tokens', 0)
        for p, p_data in stats.get('by_provider', {}).items():
            cur = all_providers.setdefault(p, _entry_default())
            if p_data.get('total_tokens', 0) > cur.get('total_tokens', 0):
                cur['total_tokens'] = p_data.get('total_tokens', 0)
                cur['prompt_tokens'] = p_data.get('prompt_tokens', 0)
                cur['completion_tokens'] = p_data.get('completion_tokens', 0)
            if p_data.get('request_count', 0) > cur.get('request_count', 0):
                cur['request_count'] = p_data.get('request_count', 0)

        totals = dict(stats.get('totals', {}))
        sum_req = sum(v.get('request_count', 0) for v in all_models.values())
        sum_total = sum(v.get('total_tokens', 0) for v in all_models.values())
        sum_prompt = sum(v.get('prompt_tokens', 0) for v in all_models.values())
        sum_comp = sum(v.get('completion_tokens', 0) for v in all_models.values())
        if sum_total > totals.get('total_tokens', 0):
            totals['total_tokens'] = sum_total
            totals['prompt_tokens'] = sum_prompt
            totals['completion_tokens'] = sum_comp
        if sum_req > totals.get('request_count', 0):
            totals['request_count'] = sum_req

        def _rank(items: dict, name_key: str) -> list[dict]:
            return sorted(
                [{name_key: k, **v} for k, v in items.items()],
                key=lambda x: -int(x.get('total_tokens', 0)),
            )

        return {
            'version': stats.get('version', 5),
            'updated_at': int(stats.get('updated_at', 0)),
            'last_event_ts': int(stats.get('last_event_ts', 0)),
            'totals': totals,
            'by_model': all_models,
            'by_client': all_clients,
            'by_provider': all_providers,
            'daily': {k: dict(v) for k, v in stats.get('daily', {}).items()},
            'hourly': {k: dict(v) for k, v in stats.get('hourly', {}).items()},
            'model_ranking': _rank(all_models, 'model'),
            'client_ranking': _rank(all_clients, 'client'),
            'provider_ranking': _rank(all_providers, 'provider'),
        }


def reset_cumulative_stats() -> dict:
    """重置所有累积统计（慎用）。"""
    with _CUMULATIVE_LOCK:
        stats = _default_stats()
        stats['updated_at'] = int(time.time())
        _save_stats(stats)
        return stats


def rebuild_cumulative_stats(events: list[dict] | None = None) -> dict:
    """全量重建累积统计，用于补录归档事件或修复数据。"""
    if events is None:
        events = _merge_all_events(limit=5000)

    events = sorted(events, key=lambda e: int(e.get('timestamp') or 0))

    with _CUMULATIVE_LOCK:
        stats = _default_stats()
        _rebuild_stats_internal(stats, events)
        _save_stats(stats)
        return stats
