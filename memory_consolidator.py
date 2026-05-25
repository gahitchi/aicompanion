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
import profiles
from episodic_memory import by_person

# Where consolidator state lives. Tracks last-run time so we don't summarize
# every restart.
_ROOT = Path(__file__).resolve().parent
STATE_FILE = _ROOT / "consolidator_state.json"
FOLLOWUPS_FILE = _ROOT / "followups.json"

CONSOLIDATE_INTERVAL_HRS = float(os.environ.get("CONSOLIDATE_INTERVAL_HRS", "12"))
MIN_EPISODES_TO_RUN = int(os.environ.get("CONSOLIDATE_MIN_EPISODES", "4"))
MAX_FOLLOWUPS_KEPT = 12  # ring buffer; oldest drop off


_PROMPT = """You're reading conversation transcripts between ONE PERSON and Jade
(an AI). Produce ONE JSON object with these fields:

  summary     — 2-4 sentences on what the person and Jade discussed and any
                emotional or topical arc. Don't pretend events you don't see.

  facts       — array of NEW factual statements the PERSON revealed about
                THEMSELVES (their life, projects, the people they know, etc.).
                Each must be something the PERSON actually said about
                themselves — not something Jade said, not tool output. Phrase
                each as a standalone sentence ("They live in...", "They work
                as..."). IGNORE system status, tool results, dates. [] if none.

  personality — array of short observations about HOW this person communicates
                or behaves, if clearly evidenced ("prefers blunt answers",
                "uses dark humor", "gets anxious about deadlines"). These guide
                how Jade should talk to them. [] if not clear yet. Be cautious;
                don't over-infer from one line.

  habits      — array of routines/patterns ("works late", "asks for a morning
                briefing", "exercises in the evening"). [] if none.

  likes       — array of topics this person clearly enjoys talking about. [] if
                none.

  followups   — array of short prompts Jade could naturally raise next time,
                phrased as questions about THEM ("how did your project go?").
                [] if nothing worth raising.

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


def _as_list(x) -> list:
    return x if isinstance(x, list) else []


def _consolidate_person(person: str, episodes: list) -> dict:
    """Summarize + learn from one person's recent episodes. Merges a profile
    delta (facts + personality/habits/topics) for everyone; for the owner it
    additionally writes the summary to Chroma and queues follow-ups."""
    lines = []
    for ep in episodes:
        u = (ep.get("user") or "").strip()[:300]
        a = (ep.get("ai") or "").strip()[:300]
        if u or a:
            lines.append(f"Person: {u}\nJade: {a}")
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
    followups = _as_list(parsed.get("followups"))

    # Learned profile delta — applies to every person. Implicit inference fills
    # free-text fields only; explicit settings (and dials) are never clobbered.
    merged = profiles.merge_inferred(person, {
        "facts": _as_list(parsed.get("facts")),
        "personality": _as_list(parsed.get("personality")),
        "habits": _as_list(parsed.get("habits")),
        "topics_love": _as_list(parsed.get("likes")),
    })

    # Owner-only: durable summary → Chroma; follow-ups → welcome ritual.
    if person == profiles.OWNER:
        if summary:
            try:
                memory.save_memory(
                    f"[summary {datetime.now(timezone.utc).date().isoformat()}] {summary}",
                    kind="summary",
                )
            except Exception:
                pass
        if followups:
            existing = _load_followups()
            new_items = [f.strip() for f in followups if isinstance(f, str) and f.strip()]
            _save_followups(existing + [f for f in new_items if f not in existing])

    return {
        "episodes": len(episodes),
        "summary_chars": len(summary),
        "facts": merged["facts"],
        "notes": merged["notes"],
        "followups": len(followups),
    }


def consolidate(force: bool = False) -> dict:
    """Run a consolidation pass over every person's recent episodes.

    Skips if the last run was < CONSOLIDATE_INTERVAL_HRS ago (unless force=True),
    or if there aren't enough episodes overall to bother with.
    """
    state = _load_state()
    last_ts = state.get("last_run_ts", 0.0)
    now = time.time()
    hours_since = (now - last_ts) / 3600 if last_ts else 999
    if not force and hours_since < CONSOLIDATE_INTERVAL_HRS:
        return {"skipped": "interval", "hours_since": round(hours_since, 1)}

    groups = by_person()
    total = sum(len(v) for v in groups.values())
    if total < MIN_EPISODES_TO_RUN:
        return {"skipped": "not_enough_episodes", "count": total}

    report = {"ok": True, "people": {}}
    for person, eps in groups.items():
        eps = eps[-30:]
        if len(eps) < MIN_EPISODES_TO_RUN:
            continue
        report["people"][person] = _consolidate_person(person, eps)

    state["last_run_ts"] = now
    state["last_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["last_episode_count"] = total
    _save_state(state)
    return report


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
