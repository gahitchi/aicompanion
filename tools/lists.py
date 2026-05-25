"""Simple named lists (shopping, to-do, …) persisted to a gitignored JSON file.

SAFE, not owner-only — a shared household shopping list is fine. The LLM picks a
sensible list name from the user's words ('add milk to the shopping list').
"""
import json
import threading
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "lists.json"
_LOCK = threading.Lock()


def _load() -> dict:
    try:
        return json.loads(_PATH.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        _PATH.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def add_to_list(name: str, item: str) -> str:
    """Add an item to a named list (created if new)."""
    key = (name or "list").strip().lower()
    with _LOCK:
        data = _load()
        data.setdefault(key, [])
        data[key].append(item.strip())
        _save(data)
        return f"Added '{item.strip()}' to your {key} list ({len(data[key])} items)."


def show_list(name: str = "") -> str:
    """Show one named list, or all list names if none given."""
    key = (name or "").strip().lower()
    with _LOCK:
        data = _load()
    if not data:
        return "You don't have any lists yet."
    if key:
        items = data.get(key)
        if not items:
            return f"Your {key} list is empty."
        return f"{key} list:\n" + "\n".join(f"- {i}" for i in items)
    return "Your lists: " + ", ".join(f"{k} ({len(v)})" for k, v in data.items())


def remove_from_list(name: str, item: str) -> str:
    """Remove the first matching item (case-insensitive) from a named list."""
    key = (name or "list").strip().lower()
    with _LOCK:
        data = _load()
        items = data.get(key, [])
        for idx, existing in enumerate(items):
            if existing.lower() == item.strip().lower():
                items.pop(idx)
                _save(data)
                return f"Removed '{existing}' from {key}."
        return f"'{item}' isn't on your {key} list."
