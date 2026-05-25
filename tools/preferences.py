"""Let a user shape how Jade interacts with THEM — the explicit half of the
ad-personam adaptation layer (profiles.py).

Each function writes to the *current speaker's* profile (profiles.current()),
so everyone tunes their own experience and nobody can edit someone else's.
These change DELIVERY only — the base principles live in persona.py and are not
settable here (truth, no-flattery, no-manipulation, safety all stand).
"""
import persona
import profiles


# Natural-language aliases → persona dial names.
_DIAL_ALIASES = {
    "length": "verbosity", "wordiness": "verbosity", "verbosity": "verbosity",
    "formality": "formality", "register": "formality",
    "humor": "humor", "humour": "humor", "jokes": "humor",
    "swearing": "profanity", "cursing": "profanity", "profanity": "profanity",
    "explicit": "explicit_allowed", "explicit_content": "explicit_allowed",
    "explicit_allowed": "explicit_allowed",
    "comfort": "empathy_style", "comfort_style": "empathy_style", "empathy": "empathy_style",
    "opinions": "opinion_stance", "opinion": "opinion_stance",
    "pushback": "challenge_style", "challenge": "challenge_style",
    "mood": "default_mood", "default_mood": "default_mood",
}

# free-text note kinds → profile fields
_NOTE_KINDS = {
    "do": "dos", "always": "dos",
    "dont": "donts", "never": "donts", "avoid": "donts",
    "like_topic": "topics_love", "likes": "topics_love",
    "avoid_topic": "topics_avoid", "dislikes": "topics_avoid",
    "about_me": "facts", "fact": "facts",
}

_BOOL_ON = {"on", "true", "yes", "y", "allowed", "allow", "enable", "enabled", "1"}
_BOOL_OFF = {"off", "false", "no", "n", "disallow", "disable", "disabled", "0"}


def _person() -> str | None:
    return profiles.current()


def set_preference(setting: str, value: str) -> str:
    """Set a persona dial for the current speaker (verbosity, formality, humor,
    profanity, explicit, comfort/empathy, opinions, pushback, mood)."""
    person = _person()
    if not person:
        return "There's no recognized speaker to personalize for right now."

    key = (setting or "").strip().lower().replace(" ", "_").replace("-", "_")
    trait = _DIAL_ALIASES.get(key, key)
    if trait not in persona.ADJUSTABLE_TRAITS:
        return (f"I can't tune '{setting}'. I can adjust: verbosity, formality, "
                f"humor, profanity, explicit, comfort, opinions, pushback, mood.")

    if trait == "explicit_allowed":
        v = str(value).strip().lower()
        if v in _BOOL_ON:
            on = True
        elif v in _BOOL_OFF:
            on = False
        else:
            return "For explicit content, tell me on or off."
        ok, msg = profiles.set_dial(person, trait, on)
        return msg

    # Table-backed dials use hyphenated values, e.g. 'cutting-sarcastic'.
    val = str(value).strip().lower().replace(" ", "-")
    ok, msg = profiles.set_dial(person, trait, val)
    return msg


def remember_preference(text: str, kind: str = "do") -> str:
    """Save a free-text preference/fact for the current speaker.

    kind: 'do' / 'dont' (a rule), 'like_topic' / 'avoid_topic' (topics),
    'call_me' (what to call them), or 'about_me' (a plain fact)."""
    person = _person()
    if not person:
        return "There's no recognized speaker to personalize for right now."
    text = (text or "").strip()
    if not text:
        return "Tell me the preference and I'll keep it."

    k = (kind or "do").strip().lower().replace("'", "").replace(" ", "_")
    if k in ("call_me", "address", "name", "call"):
        profiles.set_address(person, text)
        return f"Got it — I'll call you {text}."

    field = _NOTE_KINDS.get(k, "dos")
    ok, msg = profiles.add_note(person, field, text)
    return msg if ok else "Didn't catch a preference to save."


def forget_preference(text: str) -> str:
    """Remove a previously-saved free-text preference/fact for the current speaker."""
    person = _person()
    if not person:
        return "There's no recognized speaker to personalize for right now."
    text = (text or "").strip()
    if not text:
        return "Tell me which preference to drop."
    for field in ("dos", "donts", "topics_love", "topics_avoid", "facts"):
        if profiles.remove_note(person, field, text):
            return "Done — dropped that one."
    # Maybe they named a dial to reset.
    key = text.lower().replace(" ", "_").replace("-", "_")
    trait = _DIAL_ALIASES.get(key)
    if trait:
        profiles.clear_dial(person, trait)
        return f"Reset {key} back to default."
    return "I didn't have that saved."
