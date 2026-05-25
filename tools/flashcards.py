"""Spaced-repetition flashcards (Leitner system).

add_flashcard makes a card; quiz_me pulls the most-overdue card and puts Jade in a
study session-mode (session.py) so she runs the drill conversationally; review_card
grades it and reschedules — right answers move up the boxes (longer intervals),
wrong ones reset to box 1 for a same-day re-drill. flashcards_loop nudges once a
day when cards are due.

Cards live in a gitignored flashcards.json (the lists.py load/save/lock pattern).
Owner-only — it's the owner's study material. Boxes index into _INTERVALS (days).
"""
import json
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from shared_state import STOP_EVENT

_PATH = Path(__file__).resolve().parent.parent / "flashcards.json"
_LOCK = threading.Lock()
_INTERVALS = [0, 1, 2, 4, 7, 15, 30]  # days until next review, by box (1-indexed)

_STUDY_MODE = (
    "STUDY SESSION: You're quizzing the user with flashcards. Ask the question on "
    "the card's front and WAIT — do not reveal the answer. After they respond, say "
    "whether they were right (the answer is given to you), call review_card with "
    "the card id and whether they got it, then call quiz_me again for the next "
    "card. Keep it brisk and encouraging. If they want to stop, call end_game.")


def _load() -> list:
    try:
        return json.loads(_PATH.read_text())
    except Exception:
        return []


def _save(cards: list) -> None:
    try:
        _PATH.write_text(json.dumps(cards, indent=2))
    except Exception:
        pass


def _today() -> str:
    return date.today().isoformat()


def _due_cards(cards: list, deck: str = "") -> list:
    today = _today()
    deck = (deck or "").strip().lower()
    due = [c for c in cards if c.get("due", today) <= today
           and (not deck or c.get("deck", "general") == deck)]
    due.sort(key=lambda c: c.get("due", today))  # most overdue first
    return due


def add_flashcard(front: str, back: str, deck: str = "general") -> str:
    """Create a flashcard. front = the prompt/question, back = the answer."""
    front, back = (front or "").strip(), (back or "").strip()
    if not front or not back:
        return "I need both a question and an answer for the card."
    deck = (deck or "general").strip().lower()
    with _LOCK:
        cards = _load()
        cards.append({"id": uuid.uuid4().hex[:8], "front": front, "back": back,
                      "deck": deck, "box": 1, "due": _today(), "created": _today()})
        n = sum(1 for c in cards if c.get("deck") == deck)
        _save(cards)
    return f"Added that card to your {deck} deck ({n} card{'s' if n != 1 else ''})."


def quiz_me(deck: str = "") -> str:
    """Start (or continue) a review of due cards. Picks the most overdue card and
    has Jade quiz you on it."""
    import session
    with _LOCK:
        cards = _load()
    due = _due_cards(cards, deck)
    if not due:
        where = f" in your {deck.strip().lower()} deck" if deck.strip() else ""
        return f"No cards are due for review{where} right now — nicely done."
    c = due[0]
    session.set_mode("game", _STUDY_MODE, "study")
    # The answer is returned for the model's grading only; the study-mode prompt
    # tells it not to reveal the answer until the user has tried.
    return (f"[{len(due)} due] card {c['id']} — Q: {c['front']} | A (for grading, "
            f"don't reveal yet): {c['back']}")


def review_card(id: str, correct: bool) -> str:
    """Grade a card after the user's answer: correct moves it up a box (longer "
    interval); wrong sends it back to box 1 for a same-day re-drill."""
    with _LOCK:
        cards = _load()
        for c in cards:
            if c.get("id") == id:
                if correct:
                    c["box"] = min(c.get("box", 1) + 1, len(_INTERVALS) - 1)
                else:
                    c["box"] = 1
                days = _INTERVALS[c["box"]]
                c["due"] = (date.today() + timedelta(days=days)).isoformat()
                _save(cards)
                when = "later today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
                return f"{'Nice' if correct else 'No worries'} — I'll bring that one back {when}."
        return f"I couldn't find a card with id {id}."


def flashcards_loop(queue) -> None:
    """Once daily at JADE_FLASHCARDS_TIME, nudge if any cards are due."""
    try:
        hh, mm = [int(x) for x in os.environ.get("JADE_FLASHCARDS_TIME", "18:00").split(":")]
    except Exception:
        hh, mm = 18, 0
    last_date = None
    while not STOP_EVENT.is_set():
        now = datetime.now()
        if (now.hour, now.minute) == (hh, mm) and now.date() != last_date:
            last_date = now.date()
            try:
                n = len(_due_cards(_load()))
                if n:
                    queue.append({"type": "review",
                                  "content": f"You've got {n} flashcard"
                                  f"{'s' if n != 1 else ''} ready to review whenever "
                                  f"you'd like — just say 'quiz me'."})
            except Exception:
                pass
        for _ in range(20):
            if STOP_EVENT.is_set():
                return
            time.sleep(1)
