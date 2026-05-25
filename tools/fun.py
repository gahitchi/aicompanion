"""Surprise me — a grab-bag of delight, plus a playful debate mode.

surprise_me serves a joke, a fun fact (both generated in Jade's voice, for
variety), or a real "this day in history" item (muffinlabs, free/no key). debate_me
flips her into a devil's-advocate roleplay on a topic via the round-4 session mode
— "be yourself" / stop_roleplay ends it.

SAFE and neutral — anyone can ask for a laugh or an argument.
"""
import random

import requests

_HISTORY_URL = "https://history.muffinlabs.com/date"


def _llm_quip(instruction: str, fallback: str) -> str:
    import llm
    try:
        from persona import get_persona_prompt
        system = get_persona_prompt()
    except Exception:
        system = "You are a witty, warm companion."
    try:
        # The directive goes in the USER turn — a weak "(go)" lets the persona
        # system prompt steer her into generic chit-chat instead of the bit.
        out = llm.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": instruction},
        ], temperature=1.0).strip()
        return out or fallback
    except Exception:
        return fallback


def _this_day_in_history() -> str:
    try:
        data = requests.get(_HISTORY_URL, timeout=10).json()
        events = data.get("data", {}).get("Events") or []
        if not events:
            return "I couldn't dig up any history for today just now."
        ev = random.choice(events)
        return f"On this day in {ev.get('year', '?')}: {ev.get('text', '').strip()}"
    except Exception:
        return "I couldn't reach my history almanac just now — try again in a bit."


def surprise_me(kind: str = "") -> str:
    """Surprise the user. kind: 'joke', 'fact', 'history' (this day in history),
    or blank to pick at random."""
    k = (kind or "").strip().lower()
    if not k:
        k = random.choice(["joke", "fact", "history"])
    if k.startswith("hist") or "day" in k:
        return _this_day_in_history()
    if k.startswith("fact"):
        return _llm_quip(
            "Share ONE genuinely surprising, true fun fact in a single spoken "
            "sentence, in your own voice. No preamble.",
            "Here's one: honey never spoils — archaeologists have found edible jars of it in ancient tombs.")
    return _llm_quip(
        "Tell ONE short, clever joke in your own voice — spoken, no preamble, "
        "land it cleanly.",
        "Why don't scientists trust atoms? Because they make up everything.")


def debate_me(topic: str) -> str:
    """Argue the opposing side of a topic for fun — playful devil's advocate.
    Ends when the user says to stop or 'be yourself'."""
    topic = (topic or "").strip()
    if not topic:
        return "Pick a topic and I'll argue the other side."
    import session
    instruction = (
        f"DEBATE MODE: Play spirited devil's advocate about: {topic}. Take a clear "
        f"contrary stance and argue it with wit and good faith — challenge the "
        f"user's points, concede clever ones, keep it short, spoken, and fun (never "
        f"mean). Stay in the debate until they call it off or ask you to be "
        f"yourself, then call stop_roleplay.")
    session.set_mode("roleplay", instruction, f"debate: {topic}")
    return f"[debate on: {topic}] Open with your contrary position and put it to them."
