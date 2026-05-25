"""Sticky per-person mood — the in-conversation register layer.

Covers: keyword detection, priority (spicy beats angry), stickiness (holds with
no keywords), decay to neutral after MOOD_DECAY_TURNS quiet turns, strong-signal
switch, per-person isolation, and the idle reset.

State is redirected to a temp file so the real mood_state.json is never touched.
Standalone (no pytest):  python tests/test_mood.py
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_failures = []


def check(name, fn):
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:  # noqa: BLE001
        _failures.append((name, e))
        print(f"FAIL  {name}: {type(e).__name__}: {e}")


def _fresh():
    import mood
    mood._PATH = Path(tempfile.mkdtemp()) / "mood_state.json"
    return mood


def _detection_and_priority():
    mood = _fresh()
    assert mood.signal_from_text("you look so sexy tonight") == "spicy"
    assert mood.signal_from_text("this is bullshit, I'm so pissed") == "angry"
    assert mood.signal_from_text("I'm exhausted and so down lately") == "sad"
    assert mood.signal_from_text("just need to fix this bug, what's the plan") == "focused"
    assert mood.signal_from_text("the weather is fine") is None
    # spicy must beat angry so "fuck me" reads spicy, not angry
    assert mood.signal_from_text("fuck me, that's hot") == "spicy"


def _stickiness_holds():
    mood = _fresh()
    assert mood.update("owner", "come here and take me to bed") == "spicy"
    # plain, keyword-free turns keep the mood (the whole point)
    assert mood.update("owner", "yeah") == "spicy"
    assert mood.update("owner", "okay") == "spicy"


def _decay_to_neutral():
    mood = _fresh()
    mood.update("owner", "you're so sexy")            # -> spicy, quiet=0
    for _ in range(mood.MOOD_DECAY_TURNS - 1):
        assert mood.update("owner", "mm") == "spicy"   # holds
    assert mood.update("owner", "anyway") == "neutral"  # decays on the Nth quiet turn


def _strong_switch():
    mood = _fresh()
    mood.update("owner", "you're gorgeous")            # spicy
    assert mood.update("owner", "ugh this is infuriating and stupid") == "angry"


def _per_person_isolation():
    mood = _fresh()
    mood.update("owner", "let's get spicy")
    mood.update("Sam", "just help me debug this")
    assert mood.current("owner") == "spicy"
    assert mood.current("Sam") == "focused"


def _idle_reset():
    mood = _fresh()
    mood.update("owner", "you're so sexy")
    assert mood.current("owner") == "spicy"
    # age the timestamp past the idle window
    data = mood._load_all()
    data["owner"]["updated_at"] = time.time() - (mood.MOOD_IDLE_RESET_MIN + 1) * 60
    mood._save_all(data)
    assert mood.current("owner") == "neutral"


if __name__ == "__main__":
    check("detection + priority", _detection_and_priority)
    check("stickiness holds with no keywords", _stickiness_holds)
    check("decays to neutral after quiet turns", _decay_to_neutral)
    check("strong signal switches instantly", _strong_switch)
    check("per-person isolation", _per_person_isolation)
    check("idle reset", _idle_reset)
    if _failures:
        print(f"\n{len(_failures)} failure(s).")
        sys.exit(1)
    print("\nAll mood-layer checks passed.")
