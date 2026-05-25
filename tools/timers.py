"""Countdown timers — distinct from reminders (no message, just 'your X is up').

Built on the persistent scheduler with kind='timer', so timers survive restarts
and fire through the same proactive voice path (ungated for timeliness). SAFE.
"""
import time

import scheduler


def _fmt(secs) -> str:
    secs = int(secs)
    if secs < 90:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60} min"
    return f"{secs // 3600}h{(secs % 3600) // 60:02d}"


def start_timer(seconds: int, label: str = "") -> str:
    """Start a countdown. She'll say 'your <label> timer is up' when it fires."""
    try:
        secs = max(1, int(seconds))
    except (TypeError, ValueError):
        return "tool_error: seconds must be a number."
    item = scheduler.add_reminder(label.strip(), time.time() + secs, kind="timer")
    name = f"{label.strip()} " if label.strip() else ""
    return f"{name}timer set for {_fmt(secs)} (id {item['id']})."


def list_timers() -> str:
    items = scheduler.list_reminders(kind="timer")
    if not items:
        return "No timers running."
    now = time.time()
    return "Timers:\n" + "\n".join(
        f"- [{t['id']}] {t['message'] or 'timer'}: {_fmt(max(0, t['run_at'] - now))} left"
        for t in items
    )


def cancel_timer(id: str) -> str:
    return f"Cancelled timer {id}." if scheduler.cancel_reminder(id) else f"No timer with id {id}."
