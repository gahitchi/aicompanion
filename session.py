"""Transient 'session mode' — a temporary instruction layered onto Jade's system
prompt for the duration of a game or a roleplay.

It's deliberately in-memory only: a restart (or a 30-min idle) drops back to plain
Jade, so a half-finished game or an abandoned character never traps her. The
games/roleplay tools (tools/modes.py) set and clear it; core/agent.py appends
active_instruction() to the per-turn context block, so the persona and its hard
rules always stay underneath — the mode is additive, never a replacement.
"""
import os
import threading
import time

_LOCK = threading.Lock()
_state = {"kind": None, "instruction": None, "label": None, "started_at": 0.0}


def _timeout() -> float:
    try:
        return float(os.environ.get("JADE_MODE_TIMEOUT", "1800"))  # 30 min
    except ValueError:
        return 1800.0


def set_mode(kind: str, instruction: str, label: str = "") -> None:
    """Activate a mode. `kind` is 'game' or 'roleplay'; `instruction` is the text
    injected into the system prompt; `label` is a short human name."""
    with _LOCK:
        _state.update(kind=kind, instruction=instruction, label=label,
                      started_at=time.time())


def clear_mode() -> None:
    with _LOCK:
        _state.update(kind=None, instruction=None, label=None, started_at=0.0)


def active() -> dict | None:
    """The active mode dict (kind/instruction/label/started_at), or None. Honors
    the idle timeout — an expired mode is cleared and reported as inactive."""
    with _LOCK:
        if not _state["instruction"]:
            return None
        if time.time() - _state["started_at"] > _timeout():
            _state.update(kind=None, instruction=None, label=None, started_at=0.0)
            return None
        return dict(_state)


def active_instruction() -> str | None:
    """Just the instruction text to inject, or None when no mode is active."""
    m = active()
    return m["instruction"] if m else None
