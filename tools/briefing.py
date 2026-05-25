"""Daily briefing + the background loops that voice it.

daily_briefing() composes a warm spoken digest from weather + today's calendar +
(optionally) unread email + a couple of headlines, phrased in-character by the
LLM. It's both an on-demand tool ("give me my briefing", owner-only — it reads
private mail/calendar) and what briefing_loop fires once each morning. nudge_loop
warns about calendar events a few minutes out.

The loops follow autonomous_loop.py: compose, append {"type","content"} to the
shared task_queue, sleep in short slices for clean shutdown. proactive_speaker
voices the items (briefing is gated by quiet hours/cooldown; nudges are not).
"""
import os
import time
from datetime import datetime, timezone

from shared_state import STOP_EVENT


def _compose_raw() -> str:
    """Gather raw facts; each tool fails open to a short string on its own."""
    parts = []
    try:
        from tools.weather import get_weather
        parts.append("Weather today: " + get_weather(when="today"))
    except Exception:
        pass
    try:
        from tools.gcal import list_events
        parts.append("Today's calendar: " + list_events("today"))
    except Exception:
        pass
    if os.environ.get("JADE_BRIEFING_INCLUDE_EMAIL", "1") == "1":
        try:
            from tools.mail import list_inbox
            parts.append("Unread email: " + list_inbox(n=5, unread_only=True))
        except Exception:
            pass
    try:
        from tools.news import get_headlines
        parts.append(get_headlines(n=3))
    except Exception:
        pass
    return "\n\n".join(p for p in parts if p.strip())


def daily_briefing() -> str:
    """Compose a short, spoken morning briefing in Jade's voice."""
    raw = _compose_raw()
    if not raw.strip():
        return "Nothing to brief on right now."
    import llm
    try:
        from persona import get_persona_prompt
        system = get_persona_prompt()
    except Exception:
        system = "You are a warm, concise voice assistant."
    user = (
        "Give the user a quick spoken morning briefing from the facts below. Be "
        "warm and natural, a few sentences, weave it together — don't read lists "
        "or markdown literally, and skip anything empty.\n\n" + raw
    )
    try:
        return llm.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            temperature=0.6,
        ).strip()
    except Exception:
        return raw  # LLM down → at least speak the raw facts


def _parse_hhmm(s: str):
    try:
        h, m = s.strip().split(":")
        return int(h), int(m)
    except Exception:
        return 8, 0


def briefing_loop(queue) -> None:
    """Fire the daily briefing once per day at JADE_BRIEFING_TIME (HH:MM, local)."""
    hh, mm = _parse_hhmm(os.environ.get("JADE_BRIEFING_TIME", "08:00"))
    last_date = None
    while not STOP_EVENT.is_set():
        now = datetime.now()
        if (now.hour, now.minute) == (hh, mm) and now.date() != last_date:
            last_date = now.date()
            try:
                text = daily_briefing()
                if text:
                    queue.append({"type": "briefing", "content": text})
            except Exception:
                pass
        for _ in range(20):  # ~20s granularity is enough to catch the minute
            if STOP_EVENT.is_set():
                return
            time.sleep(1)


def nudge_loop(queue) -> None:
    """Warn about calendar events starting within JADE_NUDGE_LEAD_MIN minutes,
    once per event id."""
    try:
        lead = int(os.environ.get("JADE_NUDGE_LEAD_MIN", "10"))
    except ValueError:
        lead = 10
    nudged = set()
    while not STOP_EVENT.is_set():
        try:
            from tools.gcal import upcoming
            now = datetime.now(timezone.utc)
            for ev in upcoming(within_min=lead):
                if ev["id"] in nudged:
                    continue
                mins = int((ev["start"] - now).total_seconds() // 60)
                when = ("now" if mins <= 0 else
                        "in a minute" if mins == 1 else f"in {mins} minutes")
                queue.append({"type": "nudge",
                              "content": f"Heads up — {ev['title']} {when}."})
                nudged.add(ev["id"])
            if len(nudged) > 200:  # bound memory; lets recurring ids re-fire later
                nudged.clear()
        except Exception:
            pass
        for _ in range(60):
            if STOP_EVENT.is_set():
                return
            time.sleep(1)
