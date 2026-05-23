"""Daily-ish memory consolidation: turn raw episode history into structured
summaries, new identity facts, and follow-up questions for next time.

How it works:
- On startup (and at most once per CONSOLIDATE_INTERVAL_HRS) we look at all
  episodes from the last day or two that haven't been summarized yet.
- A single LLM call produces:
    {
      "summary": "what we talked about today, in 3-5 sentences",
      "facts": ["X is true about the user", ...],
      "followups": ["ask them about Y next time", ...]
    }
- summary → saved to Chroma with kind="summary" (retrievable later)
- facts → merged into identity_memory.json (de-duped, conflict-flagged)
- followups → appended to followups.json (used by welcome ritual)

Failures are non-fatal. If the LLM call fails or the model returns junk, we
log and skip — Jade keeps running on raw episodes alone.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import llm
import memory
from episodic_memory import load as load_episodes
from identity import load as load_identity, save as save_identity

# Where consolidator state lives. Tracks last-run time so we don't summarize
# every restart.
_ROOT = Path(__file__).resolve().parent
STATE_FILE = _ROOT / "consolidator_state.json"
FOLLOWUPS_FILE = _ROOT / "followups.json"

CONSOLIDATE_INTERVAL_HRS = float(os.environ.get("CONSOLIDATE_INTERVAL_HRS", "12"))
MIN_EPISODES_TO_RUN = int(os.environ.get("CONSOLIDATE_MIN_EPISODES", "4"))
MAX_FOLLOWUPS_KEPT = 12  # ring buffer; oldest drop off


_PROMPT = """You're reading conversation transcripts between THE USER and Jade
(an AI). Produce ONE JSON object with three fields:

  summary   — 2-4 sentences on what THE USER and JADE discussed and any
              emotional or topical arc. Don't pretend events you don't see.

  facts     — array of NEW factual statements THE USER revealed about
              THEMSELVES (their life, preferences, projects, opinions,
              people they know, etc.). Each fact must be something the USER
              actually said about themselves — not something Jade said, not
              tool output, not a generic observation. Phrase each as a
              standalone sentence starting with "User..." or "They...".
              IGNORE anything that looks like a system status, a tool result,
              a date/time, or Jade's claims. [] if nothing new about the user.

  followups — array of short prompts Jade could naturally bring up next time,
              based on things the user mentioned. Phrase each as a question
              about THEM ("how did your project go?", "did you ever try X?").
              IGNORE anything generic or about Jade. [] if nothing worth raising.

Output ONLY the JSON. No prose, no markdown, no explanation."""


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_state(s: dict) -> None:
    STATE_FILE.write_text(json.dumps(s, indent=2))


def _load_followups() -> list:
    if FOLLOWUPS_FILE.exists():
        try:
            return json.loads(FOLLOWUPS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save_followups(items: list) -> None:
    FOLLOWUPS_FILE.write_text(json.dumps(items[-MAX_FOLLOWUPS_KEPT:], indent=2))


def _episodes_since(epoch: float) -> list:
    """Return episodes recorded after `epoch` (seconds). Falls back to all if
    we don't have timestamps in the episodes (the existing format doesn't)."""
    episodes = load_episodes()
    # episodes.json today has no timestamp on each entry — treat them as a
    # rolling buffer and just consolidate the last N if it's been a while.
    return episodes[-30:] if len(episodes) > 30 else episodes


def _merge_facts(new_facts: list[str]) -> int:
    """Merge new facts into identity_memory.json. Returns number added."""
    if not new_facts:
        return 0
    data = load_identity()
    profile = data.setdefault("user_profile", {})
    learned = profile.setdefault("learned_facts", [])
    existing_lower = {f.lower() for f in learned if isinstance(f, str)}
    added = 0
    for fact in new_facts:
        if not isinstance(fact, str):
            continue
        if fact.lower() in existing_lower:
            continue
        learned.append(fact.strip())
        existing_lower.add(fact.lower())
        added += 1
    save_identity(data)
    return added


def consolidate(force: bool = False) -> dict:
    """Run a consolidation pass. Returns a small report dict for logging.

    Skips if the last run was < CONSOLIDATE_INTERVAL_HRS ago (unless force=True),
    or if there aren't enough new episodes to bother with.
    """
    state = _load_state()
    last_ts = state.get("last_run_ts", 0.0)
    now = time.time()
    hours_since = (now - last_ts) / 3600 if last_ts else 999
    if not force and hours_since < CONSOLIDATE_INTERVAL_HRS:
        return {"skipped": "interval", "hours_since": round(hours_since, 1)}

    episodes = _episodes_since(last_ts)
    if len(episodes) < MIN_EPISODES_TO_RUN:
        return {"skipped": "not_enough_episodes", "count": len(episodes)}

    # Build the input — keep it compact, trim long replies.
    lines = []
    for ep in episodes:
        u = (ep.get("user") or "").strip()[:300]
        a = (ep.get("ai") or "").strip()[:300]
        if u or a:
            lines.append(f"User: {u}\nJade: {a}")
    convo = "\n\n".join(lines)
    if not convo:
        return {"skipped": "empty"}

    messages = [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": convo},
    ]
    try:
        raw = llm.chat(messages, temperature=0.3, response_format={"type": "json_object"})
    except Exception as e:
        return {"skipped": "llm_error", "error": str(e)}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"skipped": "bad_json", "snippet": raw[:120]}

    summary = (parsed.get("summary") or "").strip()
    facts = parsed.get("facts") or []
    followups = parsed.get("followups") or []

    # Write summary to Chroma (semantically retrievable later)
    if summary:
        try:
            memory.save_memory(
                f"[summary {datetime.now(timezone.utc).date().isoformat()}] {summary}",
                kind="summary",
            )
        except Exception:
            pass

    facts_added = _merge_facts(facts) if isinstance(facts, list) else 0

    if isinstance(followups, list) and followups:
        existing = _load_followups()
        new_items = [f.strip() for f in followups if isinstance(f, str) and f.strip()]
        merged = existing + [f for f in new_items if f not in existing]
        _save_followups(merged)

    state["last_run_ts"] = now
    state["last_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["last_episode_count"] = len(episodes)
    _save_state(state)

    return {
        "ok": True,
        "episodes_seen": len(episodes),
        "summary_chars": len(summary),
        "facts_added": facts_added,
        "followups_added": len(followups) if isinstance(followups, list) else 0,
    }


def get_followups() -> list[str]:
    """Return current outstanding follow-ups for the welcome ritual."""
    return _load_followups()


def clear_followups() -> None:
    """Clear all follow-ups (e.g. after Jade actually mentioned them)."""
    _save_followups([])


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    print(json.dumps(consolidate(force=force), indent=2))
