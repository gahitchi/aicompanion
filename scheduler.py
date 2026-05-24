"""Persistent reminder scheduler.

Reminders survive restarts (`reminders.json`). `scheduler_loop` fires due
reminders onto the shared task_queue as speakable events; the proactive speaker
in the voice loop voices them. `tools/reminders.py` is what the LLM calls to
create / list / cancel them.
"""
import json
import threading
import time
import uuid
from pathlib import Path

from shared_state import STOP_EVENT

_PATH = Path(__file__).resolve().parent / "reminders.json"
_LOCK = threading.Lock()
TASKS = []  # [{"id", "message", "run_at", "created"}]


def _load() -> None:
    global TASKS
    with _LOCK:
        if _PATH.exists():
            try:
                TASKS = json.loads(_PATH.read_text())
            except Exception:
                TASKS = []


def _save_locked() -> None:
    try:
        _PATH.write_text(json.dumps(TASKS, indent=2))
    except Exception:
        pass


def add_reminder(message: str, run_at: float) -> dict:
    """Schedule `message` to fire at epoch `run_at`. Returns the stored item."""
    item = {
        "id": uuid.uuid4().hex[:8],
        "message": message.strip(),
        "run_at": float(run_at),
        "created": time.time(),
    }
    with _LOCK:
        TASKS.append(item)
        _save_locked()
    return item


def list_reminders() -> list:
    with _LOCK:
        return sorted((dict(t) for t in TASKS), key=lambda t: t["run_at"])


def cancel_reminder(rid: str) -> bool:
    with _LOCK:
        before = len(TASKS)
        TASKS[:] = [t for t in TASKS if t["id"] != rid]
        removed = len(TASKS) < before
        if removed:
            _save_locked()
    return removed


def get_due_tasks() -> list:
    now = time.time()
    with _LOCK:
        due = [t for t in TASKS if t["run_at"] <= now]
        if due:
            TASKS[:] = [t for t in TASKS if t["run_at"] > now]
            _save_locked()
    return due


def add_task(task, delay_seconds) -> dict:
    """Back-compat shim for the old API (arbitrary payload + relative delay)."""
    msg = task if isinstance(task, str) else json.dumps(task)
    return add_reminder(msg, time.time() + delay_seconds)


def scheduler_loop(queue) -> None:
    _load()
    while not STOP_EVENT.is_set():
        for t in get_due_tasks():
            queue.append({
                "type": "reminder",
                "content": f"Reminder: {t['message']}",
                "id": t["id"],
            })
        time.sleep(1)
