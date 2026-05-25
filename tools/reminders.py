"""Reminder tools the LLM calls when the user asks to be reminded of something.

The model does the natural-language → structured conversion ("remind me in 20
minutes to call mom" → set_reminder(message="call mom", in_seconds=1200)). These
functions just validate, schedule via the persistent scheduler, and return a
short human confirmation string. Due reminders are spoken by the voice loop.
"""
import time
from datetime import datetime, timedelta

import scheduler


def _fmt_when(run_at: float) -> str:
    delta = max(0, int(run_at - time.time()))
    if delta < 90:
        return f"in {delta}s"
    if delta < 3600:
        return f"in {delta // 60} min"
    when = datetime.fromtimestamp(run_at)
    return when.strftime("at %H:%M" if delta < 86400 else "on %b %d %H:%M")


def _parse_at_time(at_time: str) -> float:
    """Parse 'HH:MM' (next occurrence) or an ISO datetime into an epoch."""
    at_time = at_time.strip()
    try:
        return datetime.fromisoformat(at_time).timestamp()
    except ValueError:
        pass
    # "HH:MM" — today if still ahead, otherwise tomorrow.
    t = datetime.strptime(at_time, "%H:%M").time()
    now = datetime.now()
    target = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target.timestamp()


def set_reminder(message: str, in_seconds: int = None, at_time: str = None) -> str:
    """Schedule a spoken reminder. Provide exactly one of in_seconds / at_time."""
    if not message or not message.strip():
        return "tool_error: reminder needs a message."
    if in_seconds is not None:
        try:
            run_at = time.time() + max(1, int(in_seconds))
        except (TypeError, ValueError):
            return "tool_error: in_seconds must be a number."
    elif at_time:
        try:
            run_at = _parse_at_time(at_time)
        except ValueError:
            return f"tool_error: couldn't parse at_time {at_time!r} (use 'HH:MM' or ISO)."
    else:
        return "tool_error: provide in_seconds or at_time."

    item = scheduler.add_reminder(message, run_at)
    return f"Reminder set {_fmt_when(run_at)}: {item['message']} (id {item['id']})."


def list_reminders() -> str:
    items = scheduler.list_reminders(kind="reminder")
    if not items:
        return "No reminders set."
    return "Reminders:\n" + "\n".join(
        f"- [{it['id']}] {_fmt_when(it['run_at'])}: {it['message']}" for it in items
    )


def cancel_reminder(id: str) -> str:
    return f"Cancelled reminder {id}." if scheduler.cancel_reminder(id) \
        else f"No reminder with id {id}."
