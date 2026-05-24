"""Lightweight profiles for recognized non-owner speakers (household members).

Keeps name + first/last-seen + a few free-form facts in people.json. This is
deliberately small: known guests are greeted by name and their turns don't
pollute the owner's private memory, but we don't keep a full per-person memory
store yet. The owner's memory still lives in the existing identity / episodic /
Chroma files.
"""
import json
from datetime import datetime
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "people.json"


def _load() -> dict:
    if _PATH.exists():
        try:
            return json.loads(_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save(d: dict) -> None:
    try:
        _PATH.write_text(json.dumps(d, indent=2))
    except Exception:
        pass


def record_seen(name: str) -> None:
    """Stamp that we just talked to `name` (creating the profile if new)."""
    if not name:
        return
    d = _load()
    now = datetime.now().isoformat(timespec="seconds")
    person = d.setdefault(name, {"facts": [], "first_seen": now})
    person["last_seen"] = now
    _save(d)


def facts_text(name: str) -> str:
    """A short line of what we know about `name`, or '' if nothing yet."""
    if not name:
        return ""
    person = _load().get(name)
    if person and person.get("facts"):
        return "What you know about them: " + "; ".join(person["facts"][:5])
    return ""
