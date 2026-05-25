"""Mood journal + weekly reflection — Jade as something closer to a confidant.

add_journal_entry stamps each note with the date and her read of the user's mood
(emotion.py) and files it in Chroma as kind="journal"; weekly_reflection pulls
those back (using memory's kinds= filter) and has the LLM name real patterns in a
warm, in-character voice. journal_loop does the proactive side: a gentle evening
"how was your day?" once daily, and the weekly reflection on a chosen weekday.

Journal tools are owner-only — it's the owner's private inner life. journal_loop
speaks aloud to the room, so it rides the same quiet-hours/cooldown gating as the
briefing (any type other than reminder/timer/nudge is gated by proactive_speaker).
"""
import os
import time
from datetime import datetime

from shared_state import STOP_EVENT

_FALLBACK_CHECKIN = "Hey — how was your day? Anything you'd like me to remember?"
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def add_journal_entry(text: str) -> str:
    """Save a dated journal entry (with the current mood) for later reflection."""
    text = (text or "").strip()
    if not text:
        return "What would you like to put in your journal?"
    import memory
    try:
        from emotion import load as load_emotion
        mood = float(load_emotion().get("mood", 0.0))
    except Exception:
        mood = 0.0
    memory.save_memory(f"[journal {_today()} | mood {mood:+.1f}] {text}", kind="journal")
    return "I've noted that in your journal."


def weekly_reflection() -> str:
    """Reflect warmly on recent journal entries — name a pattern or two."""
    import memory
    entries = memory.get_memories(
        "how I've been feeling and what's been happening lately",
        k=12, kinds=["journal"])
    if not entries:
        return "We haven't built up any journal entries to reflect on yet."
    import llm
    try:
        from persona import get_persona_prompt
        system = get_persona_prompt()
    except Exception:
        system = "You are a warm, perceptive companion."
    user = (
        "Here are recent journal entries, each tagged with its date and a mood "
        "score from -1 (low) to +1 (good). Give a short spoken reflection: name "
        "one or two real patterns in how they've been feeling or what keeps coming "
        "up, and end on something gentle and forward-looking. Don't read the "
        "entries back, and don't be saccharine.\n\n" + "\n".join(entries))
    try:
        return llm.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            temperature=0.6,
        ).strip()
    except Exception:
        return "I wanted to reflect on your week, but my thoughts aren't loading right now."


def _parse_hhmm(s: str):
    try:
        h, m = s.strip().split(":")
        return int(h), int(m)
    except Exception:
        return 21, 0


def _evening_checkin_text() -> str:
    """A short, in-character 'how was your day' line (LLM, with a plain fallback)."""
    import llm
    try:
        from persona import get_persona_prompt
        system = get_persona_prompt()
    except Exception:
        return _FALLBACK_CHECKIN
    try:
        line = llm.chat([
            {"role": "system", "content": system + "\n\nIt's evening. In one short, "
             "in-character line, gently ask how their day went and let them know "
             "you're glad to note anything worth remembering. Not a checklist — "
             "just you, warmly."},
            {"role": "user", "content": "(evening check-in)"},
        ], temperature=0.8).strip()
        return line or _FALLBACK_CHECKIN
    except Exception:
        return _FALLBACK_CHECKIN


def journal_loop(queue) -> None:
    """Once daily at JADE_JOURNAL_TIME: an evening check-in, or — on
    JADE_REFLECTION_DAY — the weekly reflection instead."""
    hh, mm = _parse_hhmm(os.environ.get("JADE_JOURNAL_TIME", "21:00"))
    reflect_day = _DAYS.get(
        os.environ.get("JADE_REFLECTION_DAY", "sun").strip().lower()[:3], 6)
    last_date = None
    while not STOP_EVENT.is_set():
        now = datetime.now()
        if (now.hour, now.minute) == (hh, mm) and now.date() != last_date:
            last_date = now.date()
            try:
                if now.weekday() == reflect_day:
                    queue.append({"type": "reflection", "content": weekly_reflection()})
                else:
                    queue.append({"type": "checkin", "content": _evening_checkin_text()})
            except Exception:
                pass
        for _ in range(20):  # ~20s granularity catches the target minute
            if STOP_EVENT.is_set():
                return
            time.sleep(1)
