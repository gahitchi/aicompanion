"""Per-person 'ad personam' profiles — what Jade has learned about each person
and how they like her to interact.

This is layer 2 of the persona stack (see persona.py): the BASE PRINCIPLES are
invariant; this layer adapts the DELIVERY per user. Two kinds of adaptation
live here:

  - dials      — per-user overrides of persona's ADJUSTABLE_TRAITS (verbosity,
                 humor, formality, profanity, explicit_allowed, …). Applied by
                 passing `overrides(person)` into persona.get_persona_prompt.
  - free-text  — address term, topics they love/avoid, explicit do's/don'ts,
                 plus observed personality/habits and plain facts. Rendered into
                 a prompt block by `adaptation_prompt(person)`.

Both fill from two sources (see core/agent.py + tools/preferences.py +
memory_consolidator.py):
  - explicit  — the user states a preference; a tool writes it. Authoritative.
  - implicit  — the consolidator infers style/personality/habits from episodes.
                Advisory; explicit dials always win.

Storage: one JSON file `profiles.json`, keyed by person id. The owner is the
id "owner"; recognized household members are keyed by their enrolled name.
Guests are never stored (they leave no trace, by privacy design).

The store holds personal data (preferences, personality, facts) — it is
gitignored and must never be committed.
"""
import json
import threading
from datetime import datetime
from pathlib import Path

import persona

_PATH = Path(__file__).resolve().parent / "profiles.json"
_LOCK = threading.RLock()

OWNER = "owner"

# Free-text adaptation fields that are append-style lists.
_LIST_FIELDS = ("topics_love", "topics_avoid", "dos", "donts", "personality", "habits")

# Which free-text fields the implicit (inferred) learner may write. `dos`/`donts`
# and `address_as` are reserved for explicit statements — we don't want the model
# inventing rules the user never asked for.
INFERRABLE_FIELDS = ("personality", "habits", "topics_love", "topics_avoid")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _empty_profile() -> dict:
    return {
        "adaptation": {
            "dials": {},            # trait -> value (subset of persona.ADJUSTABLE_TRAITS)
            "address_as": None,     # what to call them
            "topics_love": [],
            "topics_avoid": [],
            "dos": [],              # explicit "always …"
            "donts": [],            # explicit "never …"
            "personality": [],      # observed traits (mostly implicit)
            "habits": [],           # observed routines/patterns (mostly implicit)
        },
        "identity": {"facts": []},  # plain facts about them
        "relationship": {"familiarity": 0.0, "trust": 0.0, "interaction_count": 0},
        "meta": {"first_seen": _now(), "last_seen": _now()},
    }


# ---------- storage --------------------------------------------------------

def _load_all() -> dict:
    with _LOCK:
        if not _PATH.exists():
            return {}
        try:
            return json.loads(_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}


def _save_all(data: dict) -> None:
    with _LOCK:
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_PATH)


def _coerce(profile: dict) -> dict:
    """Backfill any missing keys so older/partial profiles stay valid."""
    base = _empty_profile()
    base.update({k: v for k, v in profile.items() if k in base})
    a = base["adaptation"] = {**_empty_profile()["adaptation"], **profile.get("adaptation", {})}
    for f in _LIST_FIELDS:
        if not isinstance(a.get(f), list):
            a[f] = []
    base["identity"] = {**{"facts": []}, **profile.get("identity", {})}
    base["relationship"] = {**_empty_profile()["relationship"], **profile.get("relationship", {})}
    base["meta"] = {**_empty_profile()["meta"], **profile.get("meta", {})}
    return base


def get(person: str = OWNER) -> dict:
    """Return `person`'s profile, materializing a default if it's new."""
    data = _load_all()
    if person not in data:
        data[person] = _empty_profile()
        _save_all(data)
        return data[person]
    return _coerce(data[person])


def _mutate(person: str, fn) -> dict:
    """Load → apply fn(profile) in place → save. Returns the updated profile."""
    with _LOCK:
        data = _load_all()
        prof = _coerce(data.get(person) or _empty_profile())
        if person not in data:
            prof["meta"]["first_seen"] = _now()
        fn(prof)
        prof["meta"]["last_seen"] = _now()
        data[person] = prof
        _save_all(data)
        return prof


# ---------- writes (explicit + implicit) -----------------------------------

def set_dial(person: str, trait: str, value) -> tuple[bool, str]:
    """Override one adjustable persona trait for `person`. Validated against
    persona.valid_trait_values so an invalid dial/value is rejected, not stored.
    """
    if trait not in persona.ADJUSTABLE_TRAITS:
        return False, f"{trait!r} isn't an adjustable trait."
    valid = persona.valid_trait_values(trait)
    if valid is not None and value not in valid:
        return False, f"{value!r} isn't valid for {trait}; choose one of {sorted(map(str, valid))}."
    _mutate(person, lambda p: p["adaptation"]["dials"].__setitem__(trait, value))
    return True, f"Set {trait} = {value} for {person}."


def clear_dial(person: str, trait: str) -> None:
    """Drop a per-user dial override so `person` reverts to the base trait."""
    _mutate(person, lambda p: p["adaptation"]["dials"].pop(trait, None))


def set_address(person: str, name) -> None:
    _mutate(person, lambda p: p["adaptation"].__setitem__("address_as", name or None))


def add_note(person: str, field: str, text: str) -> tuple[bool, str]:
    """Append a free-text note to a list field (dos/donts/topics/personality/…)
    or a plain fact (field='facts'). De-duplicated case-insensitively."""
    text = (text or "").strip()
    if not text:
        return False, "empty note"
    if field == "facts":
        _append_unique_facts(person, [text])
        return True, f"Noted about {person}: {text}"
    if field not in _LIST_FIELDS:
        return False, f"{field!r} isn't a noteable field."

    def _add(p):
        lst = p["adaptation"][field]
        if text.lower() not in {x.lower() for x in lst}:
            lst.append(text)
    _mutate(person, _add)
    return True, f"Noted ({field}) for {person}: {text}"


def remove_note(person: str, field: str, text: str) -> bool:
    """Remove a free-text note (case-insensitive match). Returns whether it hit."""
    target = (text or "").strip().lower()
    hit = {"v": False}

    def _rm(p):
        if field == "facts":
            lst = p["identity"]["facts"]
        elif field in _LIST_FIELDS:
            lst = p["adaptation"][field]
        else:
            return
        kept = [x for x in lst if x.lower() != target]
        hit["v"] = len(kept) != len(lst)
        if field == "facts":
            p["identity"]["facts"] = kept
        else:
            p["adaptation"][field] = kept
    _mutate(person, _rm)
    return hit["v"]


def _append_unique_facts(person: str, facts: list[str]) -> int:
    added = {"n": 0}

    def _add(p):
        lst = p["identity"]["facts"]
        seen = {x.lower() for x in lst}
        for f in facts:
            f = (f or "").strip()
            if f and f.lower() not in seen:
                lst.append(f)
                seen.add(f.lower())
                added["n"] += 1
    _mutate(person, _add)
    return added["n"]


def merge_inferred(person: str, inferred: dict) -> dict:
    """Merge an implicit-learning delta from the consolidator.

    `inferred` may carry: facts (list), personality/habits/topics_* (lists),
    and dials (dict). Explicit dials already set by the user are NOT clobbered —
    inferred dials only fill empty slots. Returns a small report.
    """
    report = {"facts": 0, "notes": 0, "dials": 0}
    facts = inferred.get("facts") or []
    if isinstance(facts, list):
        report["facts"] = _append_unique_facts(person, facts)

    def _apply(p):
        a = p["adaptation"]
        for field in INFERRABLE_FIELDS:
            vals = inferred.get(field) or []
            if not isinstance(vals, list):
                continue
            seen = {x.lower() for x in a[field]}
            for v in vals:
                v = (v or "").strip()
                if v and v.lower() not in seen:
                    a[field].append(v)
                    seen.add(v.lower())
                    report["notes"] += 1
        dials = inferred.get("dials") or {}
        if isinstance(dials, dict):
            for trait, value in dials.items():
                if trait not in persona.ADJUSTABLE_TRAITS or trait in a["dials"]:
                    continue  # don't overwrite an explicit choice
                valid = persona.valid_trait_values(trait)
                if valid is None or value in valid:
                    a["dials"][trait] = value
                    report["dials"] += 1
    _mutate(person, _apply)
    return report


def record_interaction(person: str, user_text: str, ai_text: str = "") -> None:
    """Bump relationship counters from one turn (replaces identity.py's math)."""
    t = (user_text or "").lower()

    def _upd(p):
        rel = p["relationship"]
        rel["interaction_count"] += 1
        rel["familiarity"] = min(1.0, rel["familiarity"] + 0.02)
        if "thank" in t or "appreciate" in t:
            rel["trust"] = min(1.0, rel["trust"] + 0.03)
        if "stupid" in t or "useless" in t or "shut up" in t:
            rel["trust"] = max(-1.0, rel["trust"] - 0.05)
    _mutate(person, _upd)


# ---------- reads (for the agent) ------------------------------------------

def overrides(person: str = OWNER) -> dict:
    """Adjustable-trait overrides for persona.get_persona_prompt(overrides=)."""
    return dict(get(person)["adaptation"].get("dials", {}))


def adaptation_prompt(person: str = OWNER) -> str:
    """Render the per-user free-text adaptation block, or '' if nothing learned.

    Persona dial overrides are NOT described here — they're applied directly to
    the persona via overrides(). This block carries the human-readable knowledge
    (facts, personality, habits) and explicit interaction preferences, prefaced
    by the principle-boundary guardrail.
    """
    prof = get(person)
    a = prof["adaptation"]
    facts = prof["identity"].get("facts", [])
    who = "this person" if person == OWNER else person

    knows, prefs = [], []
    if facts:
        knows.append("Facts: " + "; ".join(facts[:8]) + ".")
    if a["personality"]:
        knows.append("They come across as: " + "; ".join(a["personality"][:6]) + ".")
    if a["habits"]:
        knows.append("Habits/patterns: " + "; ".join(a["habits"][:6]) + ".")

    if a.get("address_as"):
        prefs.append(f'Call them "{a["address_as"]}".')
    if a["topics_love"]:
        prefs.append("They like talking about " + ", ".join(a["topics_love"][:6]) + ".")
    if a["topics_avoid"]:
        prefs.append("Steer clear of " + ", ".join(a["topics_avoid"][:6]) + ".")
    if a["dos"]:
        prefs.append("Do: " + "; ".join(a["dos"][:6]) + ".")
    if a["donts"]:
        prefs.append("Don't: " + "; ".join(a["donts"][:6]) + ".")

    if not knows and not prefs:
        return ""

    block = [persona.ADAPTATION_BOUNDARY, ""]
    if knows:
        block.append(f"What you know about {who}: " + " ".join(knows))
    if prefs:
        block.append(f"How {who} likes you to be: " + " ".join(prefs))
    return "\n".join(block)


# ---------- current-speaker context (so tools write to the right person) ----

_current = threading.local()


def set_current(person) -> None:
    """Set the speaker for this turn/thread; the preference tool reads it."""
    _current.person = person


def current() -> str | None:
    """Who's speaking right now, or None (a guest / unset)."""
    return getattr(_current, "person", None)


# ---------- one-time migration from the legacy owner files -----------------

def migrate_legacy() -> dict:
    """Import the old single-user identity_memory.json into the owner profile.

    Idempotent: only fills the owner profile when it has no facts yet, so it's
    safe to call on every startup. Returns a small report.
    """
    legacy = Path(__file__).resolve().parent / "identity_memory.json"
    if not legacy.exists():
        return {"migrated": False, "reason": "no legacy file"}
    try:
        old = json.loads(legacy.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"migrated": False, "reason": "unreadable"}

    owner = get(OWNER)
    if owner["identity"]["facts"] or owner["adaptation"]["topics_love"]:
        return {"migrated": False, "reason": "owner profile already populated"}

    prof_old = old.get("user_profile", {})
    facts = list(prof_old.get("learned_facts", []) or [])
    interests = list(prof_old.get("interests", []) or [])
    rel = old.get("relationship_state", {})

    def _apply(p):
        p["identity"]["facts"].extend(facts)
        seen = {x.lower() for x in p["adaptation"]["topics_love"]}
        for i in interests:
            if i and i.lower() not in seen:
                p["adaptation"]["topics_love"].append(i)
        if rel:
            p["relationship"].update({
                "familiarity": rel.get("familiarity", 0.0),
                "trust": rel.get("trust", 0.0),
                "interaction_count": rel.get("interaction_count", 0),
            })
    _mutate(OWNER, _apply)
    return {"migrated": True, "facts": len(facts), "interests": len(interests)}
