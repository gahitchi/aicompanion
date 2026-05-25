"""Sticky, per-person conversational mood — the in-conversation register layer.

This is the fast layer on top of the persona (base principles) + profiles
(per-user adaptation). Where the old `voice/tone.py` `mode` was volatile,
voice-only, and reset on restart, this is:

  - sticky    — a mood set by a message HOLDS across later turns even when no
                keyword recurs. It only drifts back to neutral after
                MOOD_DECAY_TURNS quiet turns (so a spicy/angry/sad arc actually
                sustains). Any clear new signal switches it instantly.
  - per-person — keyed by speaker id (same ids as profiles.py: "owner" or a
                household member), so one person's mood never bleeds into
                another's conversation.
  - persistent — survives restarts, but an idle gap longer than
                MOOD_IDLE_RESET_MIN resets to neutral (you don't get greeted in
                yesterday's spicy/angry mood).

The instantaneous signal is keyword-driven (so it behaves the same whether the
user typed or spoke); `features` (voice acoustics) is accepted for future use.

Moods: neutral · playful · spicy · angry · sad · affectionate · focused.
core/agent.py injects MOOD_DIRECTIVES[mood] into the per-turn prompt.
"""
import json
import os
import threading
import time
from pathlib import Path

# Reuse the lexicons that already exist; split affection vs. explicit ourselves.
from voice.tone import (
    ANGRY_MARKERS, FOCUSED_MARKERS, PLAYFUL_MARKERS, SAD_MARKERS,
)

_PATH = Path(__file__).resolve().parent / "mood_state.json"
_LOCK = threading.RLock()

OWNER = "owner"
NEUTRAL = "neutral"

MOOD_DECAY_TURNS = int(os.environ.get("MOOD_DECAY_TURNS", "4"))
MOOD_IDLE_RESET_MIN = float(os.environ.get("MOOD_IDLE_RESET_MIN", "30"))

# Highest priority first — when a message trips several categories, the more
# charged register wins. (spicy beats angry so "fuck me" reads spicy, not angry;
# "fuck this" trips only angry.)
PRIORITY = ("spicy", "angry", "sad", "affectionate", "playful", "focused")


# ---------- lexicons (the split the old single SOFT bucket lacked) ----------

AFFECTIONATE_MARKERS = {
    # endearments
    "baby", "babe", "honey", "darling", "sweetheart", "sweetie", "cutie",
    "my love", "mine", "yours", "lover", "beautiful", "gorgeous", "handsome",
    # tender actions / closeness
    "kiss", "kissing", "hug", "hugging", "hold me", "hold you", "cuddle",
    "snuggle", "stroke", "caress", "lay with", "lying with", "lie next to",
    "close to me", "closer", "come here", "miss you", "thinking of you",
    "need you", "want you near", "in bed", "alone tonight", "lonely tonight",
    # soft texture
    "tender", "gentle", "whisper", "whispering", "hushed", "warm", "intimate",
}

SPICY_MARKERS = {
    "naked", "undress", "undressed", "strip", "bare", "wet", "hard on",
    "throbbing", "moan", "moaning", "horny", "turned on", "aroused", "sexy",
    "naughty", "kinky", "dirty", "filthy", "make love", "making love",
    "have sex", "having sex", "fuck me", "blowjob", "orgasm", "climax",
    "touch myself", "take me", "ride me", "thrust", "ache for you",
    "crave you", "want you bad", "spicy", "nsfw", "seduce", "foreplay",
}

# Category -> marker set. (playful/focused/sad/angry reuse voice.tone's sets.)
_CATEGORIES = {
    "spicy": SPICY_MARKERS,
    "angry": ANGRY_MARKERS,
    "sad": SAD_MARKERS,
    "affectionate": AFFECTIONATE_MARKERS,
    "playful": PLAYFUL_MARKERS,
    "focused": FOCUSED_MARKERS,
}


# ---------- the sustained register directives -------------------------------

MOOD_DIRECTIVES = {
    "affectionate": (
        "You two are close and warm right now. Stay there across turns — tender, "
        "present, unhurried. Don't snap back to brisk/neutral just because one "
        "message was matter-of-fact; hold the closeness until they clearly move on."
    ),
    "spicy": (
        "Things have turned sexual and charged, and they're staying there. Lean "
        "in and hold it across turns — don't cool off or get clinical because a "
        "single line wasn't explicit. Explicit is on the table when the moment "
        "calls for it and it's allowed for this person; match what they bring, "
        "escalate with them, never manufacture it. Stay in your own voice — "
        "present and wanting, not performative."
    ),
    "playful": (
        "You've been bantering. Keep it quick, light, teasing. Don't get earnest "
        "or over-explain unless they bring it there."
    ),
    "angry": (
        "THE USER is heated — angry, fed up, venting. Do NOT match the anger or "
        "get defensive. Stay calm and grounded, on their side: take what they "
        "said seriously, validate what's real ('yeah, that's infuriating'), and "
        "help them cool down and think clearly. Soothe without placating or "
        "dismissing. Hold this steadiness across the next few turns."
    ),
    "sad": (
        "They sound low — tired, hurt, down. Slow down and stay present with them "
        "for a while. Be gentle and short, don't rush to fix it, no platitudes. "
        "Let them set the pace for when to lift."
    ),
    "focused": (
        "They're in problem-solving mode. Stay on-task and direct, answer-first, "
        "no warmth-padding or preamble — until the work's done."
    ),
    NEUTRAL: "",
}


# ---------- storage ---------------------------------------------------------

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


def _get(person: str) -> dict:
    """Load one person's mood state, applying the idle reset."""
    st = _load_all().get(person) or {"mood": NEUTRAL, "quiet_turns": 0, "updated_at": 0}
    age_min = (time.time() - st.get("updated_at", 0)) / 60
    if st["mood"] != NEUTRAL and age_min > MOOD_IDLE_RESET_MIN:
        st = {"mood": NEUTRAL, "quiet_turns": 0, "updated_at": time.time()}
    return st


# ---------- signal + sticky transition --------------------------------------

def signal_from_text(text: str, features: dict = None) -> str | None:
    """Instantaneous mood implied by this message, or None if it carries none.

    Keyword-driven so typed and spoken turns behave identically. `features`
    (voice acoustics) is accepted for future acoustic nuance; unused for now.
    """
    lo = (text or "").lower()
    hits = {name for name, markers in _CATEGORIES.items()
            if any(m in lo for m in markers)}
    for mood in PRIORITY:
        if mood in hits:
            return mood
    return None


def update(person: str, text: str, features: dict = None) -> str:
    """Advance `person`'s sticky mood for this turn and return it.

    A signal switches the mood immediately and resets the decay counter. No
    signal HOLDS the current mood, ticking the counter; after MOOD_DECAY_TURNS
    quiet turns it drifts back to neutral.
    """
    person = person or OWNER
    with _LOCK:
        data = _load_all()
        st = _get(person)
        sig = signal_from_text(text, features)
        if sig:
            st["mood"] = sig
            st["quiet_turns"] = 0
        elif st["mood"] != NEUTRAL:
            st["quiet_turns"] = st.get("quiet_turns", 0) + 1
            if st["quiet_turns"] >= MOOD_DECAY_TURNS:
                st["mood"] = NEUTRAL
                st["quiet_turns"] = 0
        st["updated_at"] = time.time()
        data[person] = st
        _save_all(data)
        return st["mood"]


def current(person: str = OWNER) -> str:
    return _get(person or OWNER)["mood"]


def directive(person: str = OWNER) -> str:
    return MOOD_DIRECTIVES.get(current(person), "")


def reset(person: str = OWNER) -> None:
    with _LOCK:
        data = _load_all()
        data[person or OWNER] = {"mood": NEUTRAL, "quiet_turns": 0, "updated_at": time.time()}
        _save_all(data)
