"""In-process event bus for the dashboard.

The voice loop, chat handlers, and tool registry publish events here. The
FastAPI `/events` WebSocket endpoint subscribes and streams them out to the
browser. Buffered to last 200 events so a fresh client gets recent context.

Events are dicts with at minimum a `type` field. Examples:
  {"type": "status", "state": "listening"}
  {"type": "heard", "text": "...", "tone": "soft", "mode": "intimate", "rms": 410}
  {"type": "said", "text": "...", "tone": "soft", "mode": "intimate"}
  {"type": "tool", "tool": "list_dir", "args": {...}, "result": "..."}
"""
import datetime
import threading
from collections import deque

_LOG_MAX = 200
_log: deque = deque(maxlen=_LOG_MAX)
_lock = threading.Lock()
_subscribers: list = []  # list of callables (event_dict) -> None


def publish(event: dict) -> None:
    """Add an event to the log and notify all subscribers."""
    event = {"t": datetime.datetime.now().isoformat(timespec="seconds"), **event}
    with _lock:
        _log.append(event)
        subs = list(_subscribers)
    for sub in subs:
        try:
            sub(event)
        except Exception:
            pass


def recent(limit: int = 50) -> list:
    """Snapshot of the last `limit` events for initial page hydration."""
    with _lock:
        items = list(_log)
    return items[-limit:]


def subscribe(callback) -> None:
    """Register a callable to receive every new event. Use with `unsubscribe`."""
    with _lock:
        _subscribers.append(callback)


def unsubscribe(callback) -> None:
    with _lock:
        if callback in _subscribers:
            _subscribers.remove(callback)
