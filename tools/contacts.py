"""A small personal contacts book — name → email / phone / note.

Persisted to a gitignored contacts.json beside the app (same load/save/lock
pattern as tools/lists.py). Registered **owner_only**: a household member or
guest can't read or edit the owner's contacts, and the tools are withheld from
their schema entirely.

Its main job beyond "what's mom's number" is resolving a spoken name to an email
address so send_email (tools/mail.py) can take "Mom" instead of a raw address —
see resolve_email(), which mail.py calls before confirming the send.
"""
import json
import threading
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "contacts.json"
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


def _key(name: str) -> str:
    return (name or "").strip().lower()


def add_contact(name: str, email: str = "", phone: str = "", note: str = "") -> str:
    """Add or update a contact. Only the fields you pass are changed; the rest of
    an existing contact is kept."""
    name = (name or "").strip()
    if not name:
        return "I need a name to save a contact."
    with _LOCK:
        data = _load()
        entry = data.get(_key(name), {"name": name})
        entry["name"] = name  # keep the nicely-cased display name
        if email.strip():
            entry["email"] = email.strip()
        if phone.strip():
            entry["phone"] = phone.strip()
        if note.strip():
            entry["note"] = note.strip()
        data[_key(name)] = entry
        _save(data)
    bits = [k for k in ("email", "phone", "note") if entry.get(k)]
    return f"Saved {name}" + (f" ({', '.join(bits)})." if bits else ".")


def show_contacts(name: str = "") -> str:
    """Show one contact's details, or all contact names if none is given."""
    with _LOCK:
        data = _load()
    if not data:
        return "You don't have any contacts saved yet."
    if name.strip():
        entry = data.get(_key(name))
        if not entry:
            return f"I don't have a contact named '{name.strip()}'."
        lines = [entry.get("name", name.strip())]
        for label in ("email", "phone", "note"):
            if entry.get(label):
                lines.append(f"  {label}: {entry[label]}")
        return "\n".join(lines)
    return "Your contacts: " + ", ".join(e.get("name", k) for k, e in data.items())


def remove_contact(name: str) -> str:
    """Delete a contact by name."""
    with _LOCK:
        data = _load()
        if _key(name) in data:
            removed = data.pop(_key(name))
            _save(data)
            return f"Removed {removed.get('name', name.strip())} from your contacts."
        return f"I don't have a contact named '{name.strip()}'."


def resolve_email(who: str):
    """Resolve a recipient to (address, label) for send_email, or None.

    'who' may already be an address ('@' present) → (who, who); otherwise it's
    treated as a contact name → (email, 'Name <email>'). Returns None when the
    name is unknown or has no email on file, so the caller can prompt for one."""
    who = (who or "").strip()
    if not who:
        return None
    if "@" in who:
        return who, who
    entry = _load().get(_key(who))
    if entry and entry.get("email"):
        return entry["email"], f"{entry.get('name', who)} <{entry['email']}>"
    return None
