"""Background watcher for automatic egress proxy adaptation.

Monitors TUN adapter and Windows system proxy changes in the background.
When network state changes (e.g. user toggles TUN or System Proxy in Clash Verge),
automatically rebuilds the runtime config so the Go core reloads the new
proxy setting via fsnotify without requiring a process restart.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from backend.state import load_state

logger = logging.getLogger('dashboard.egress_watcher')

_WATCHER_THREAD: threading.Thread | None = None
_WATCHER_STOP_EVENT = threading.Event()
_LAST_STATE: dict[str, Any] = {'mode': None, 'proxy_url': None}


def _poll_network_state() -> dict[str, Any]:
    try:
        from backend.local_proxy import detect_smart_egress_proxy
        return detect_smart_egress_proxy()
    except Exception as exc:
        return {'ok': False, 'mode': 'error', 'proxy_url': 'direct', 'error': str(exc)}


def _watcher_loop(interval_seconds: float = 3.0):
    global _LAST_STATE
    while not _WATCHER_STOP_EVENT.wait(interval_seconds):
        try:
            state = load_state()
            if not state.get('proxy_auto_detect', True):
                continue

            current = _poll_network_state()
            current_mode = current.get('mode')
            current_url = current.get('proxy_url')

            last_mode = _LAST_STATE.get('mode')
            last_url = _LAST_STATE.get('proxy_url')

            if last_mode is None:
                _LAST_STATE = {'mode': current_mode, 'proxy_url': current_url}
                continue

            if current_mode != last_mode or current_url != last_url:
                logger.info(
                    'Network egress state changed: %s (%s) -> %s (%s). Auto-adapting runtime config...',
                    last_mode, last_url, current_mode, current_url
                )
                print(
                    f'[EgressWatcher] Network egress changed: {last_mode} ({last_url}) -> {current_mode} ({current_url}). Auto-adapting runtime config...'
                )
                _LAST_STATE = {'mode': current_mode, 'proxy_url': current_url}
                try:
                    from backend.auth import rebuild_runtime_config_from_state
                    rebuild_runtime_config_from_state()
                except Exception as exc:
                    logger.error('Failed to rebuild runtime config on network change: %s', exc)
        except Exception as exc:
            logger.debug('Egress watcher poll error: %s', exc)


def start_egress_watcher(interval_seconds: float = 3.0) -> None:
    """Start background egress adaptation watcher thread if not already running."""
    global _WATCHER_THREAD
    if _WATCHER_THREAD and _WATCHER_THREAD.is_alive():
        return
    _WATCHER_STOP_EVENT.clear()
    _WATCHER_THREAD = threading.Thread(
        target=_watcher_loop,
        args=(interval_seconds,),
        name='EgressWatcherThread',
        daemon=True,
    )
    _WATCHER_THREAD.start()


def stop_egress_watcher() -> None:
    """Stop background egress adaptation watcher thread."""
    global _WATCHER_THREAD
    _WATCHER_STOP_EVENT.set()
    if _WATCHER_THREAD:
        _WATCHER_THREAD.join(timeout=2.0)
        _WATCHER_THREAD = None


def get_egress_watcher_status() -> dict[str, Any]:
    """Get live status of the egress watcher for diagnostics or UI indicators."""
    alive = bool(_WATCHER_THREAD and _WATCHER_THREAD.is_alive())
    return {
        'running': alive,
        'last_state': dict(_LAST_STATE),
    }
