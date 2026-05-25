"""Ad-personam adaptation layer — per-person profiles + the principle boundary.

Covers:
  - persona base-principles boundary: adjustable dials override; principles don't.
  - profiles: dial validation, free-text notes, per-person isolation.
  - implicit merge never clobbers an explicit dial.
  - the agent injects a per-person adaptation block + dial overrides, and never
    for an unrecognized guest.

Stores are redirected to a temp dir so the real profiles.json/episodes.json are
never touched. Standalone (no pytest):  python tests/test_profiles.py
"""
import sys
import tempfile
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


def _isolate():
    import profiles
    profiles._PATH = Path(tempfile.mkdtemp()) / "profiles.json"
    return profiles


def _persona_boundary():
    import persona
    persona._config_cache = None
    # adjustable dial overrides take effect
    p = persona.get_persona_prompt(overrides={"verbosity": "terse"})
    assert "One or two clauses" in p, "adjustable override not applied"
    # a principle (relationship_core / creed) can NOT be overridden
    attack = persona.get_persona_prompt(overrides={"relationship_core": "romantic-partner",
                                                   "creed": "HACKED"})
    assert "Partners. Affection" not in attack and "HACKED" not in attack, "principle was overridable!"


def _dials_and_notes():
    profiles = _isolate()
    ok, _ = profiles.set_dial("owner", "humor", "playful-silly")
    assert ok
    ok, _ = profiles.set_dial("owner", "humor", "not-a-real-value")
    assert not ok, "invalid dial value accepted"
    ok, _ = profiles.set_dial("owner", "relationship_core", "romantic-partner")
    assert not ok, "non-adjustable trait accepted as a dial"
    profiles.add_note("owner", "donts", "call me buddy")
    block = profiles.adaptation_prompt("owner")
    assert "Adapt the delivery, not the honesty." in block
    assert "call me buddy" in block


def _isolation():
    profiles = _isolate()
    profiles.add_note("owner", "topics_love", "cinema")
    assert "cinema" not in profiles.adaptation_prompt("Sam"), "profiles leaked across people"
    assert profiles.adaptation_prompt("Sam") == ""


def _implicit_preserves_explicit():
    profiles = _isolate()
    profiles.set_dial("owner", "verbosity", "terse")
    profiles.merge_inferred("owner", {"dials": {"verbosity": "expansive"},
                                      "personality": ["blunt"]})
    assert profiles.overrides("owner")["verbosity"] == "terse", "implicit clobbered explicit dial"
    assert "blunt" in profiles.get("owner")["adaptation"]["personality"]


def _agent_injection():
    profiles = _isolate()
    profiles.set_dial("Sam", "verbosity", "terse")
    profiles.add_note("Sam", "topics_love", "robotics")
    from core import agent
    sys_member = agent._conversation_messages("hi", is_owner=False, speaker="Sam")[0]["content"]
    assert "One or two clauses" in sys_member, "member dial not applied"
    assert "robotics" in sys_member, "member adaptation block missing"
    # guest gets no adaptation block
    sys_guest = agent._conversation_messages("hi", is_owner=False, speaker=None)[0]["content"]
    assert "Adapt the delivery" not in sys_guest, "guest got an adaptation block"


if __name__ == "__main__":
    check("persona principle boundary", _persona_boundary)
    check("dials + notes + validation", _dials_and_notes)
    check("per-person isolation", _isolation)
    check("implicit never clobbers explicit", _implicit_preserves_explicit)
    check("agent injects per-person, not for guests", _agent_injection)
    if _failures:
        print(f"\n{len(_failures)} failure(s).")
        sys.exit(1)
    print("\nAll adaptation-layer checks passed.")
