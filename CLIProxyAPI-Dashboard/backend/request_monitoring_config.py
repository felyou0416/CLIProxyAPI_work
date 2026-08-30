"""Dashboard request-observability configuration.

These settings describe the Dashboard's request monitor. They are separate
from CPA's own ``logging-to-file`` runtime option.
"""

DEFAULT_REQUEST_MONITORING_CONFIG = {
    'request_monitoring_enabled': True,
    'request_observability_refresh_seconds': 15,
    'request_events_cache_ttl_seconds': 30,
    'request_log_keep_files': 300,
    'request_event_archive_keep_entries': 20000,
}

_REQUEST_MONITORING_BOUNDS = {
    'request_observability_refresh_seconds': (5, 300),
    'request_events_cache_ttl_seconds': (5, 300),
    'request_log_keep_files': (50, 10000),
    'request_event_archive_keep_entries': (1000, 1000000),
}


def _as_bool(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        token = value.strip().lower()
        if token in ('1', 'true', 'yes', 'on'):
            return True
        if token in ('0', 'false', 'no', 'off', ''):
            return False
    return bool(value)


def _bounded_int(value, default, lower, upper):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(upper, parsed))


def normalize_request_monitoring_config(state=None):
    """Return a complete, bounded Dashboard request-monitoring config."""
    raw = state if isinstance(state, dict) else {}
    config = dict(DEFAULT_REQUEST_MONITORING_CONFIG)
    config['request_monitoring_enabled'] = _as_bool(
        raw.get('request_monitoring_enabled'),
        config['request_monitoring_enabled'],
    )
    for key, (lower, upper) in _REQUEST_MONITORING_BOUNDS.items():
        config[key] = _bounded_int(raw.get(key), config[key], lower, upper)
    return config


def load_request_monitoring_config():
    """Load Dashboard-owned settings without creating an import cycle."""
    from backend.state import load_state

    return normalize_request_monitoring_config(load_state())


def request_monitoring_enabled(state=None):
    if state is None:
        return bool(load_request_monitoring_config()['request_monitoring_enabled'])
    return bool(normalize_request_monitoring_config(state)['request_monitoring_enabled'])
