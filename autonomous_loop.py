"""Proactive autonomous loop. Decides when to speak unprompted based on the
relationship + emotional state and the open threads the consolidator surfaced,
then generates an in-character message via the LLM and enqueues it. The
proactive speaker (voice loop) decides the right moment to actually voice it."""
import os
import random
import time

import llm
import memory as memory_mod
import profiles
from emotion import load as load_emotion
from persona import get_persona_prompt
from shared_state import add_log, STOP_EVENT


# How often to consider speaking up. Was 120s (far too chatty); default 15 min.
TICK_SECONDS = int(os.environ.get("JADE_PROACTIVE_INTERVAL", "900"))
_QUIET_START = int(os.environ.get("JADE_QUIET_START", "23"))
_QUIET_END = int(os.environ.get("JADE_QUIET_END", "8"))


INTENT_HINTS = {
    "check_in": "Briefly check in with the user about what they were working on. Don't be saccharine.",
    "support_message": "The user's mood seems low. Offer a short, low-pressure opening to talk. Don't be performative.",
    "curious_prompt": "Ask one open, genuinely curious question about a project or interest the user has mentioned.",
    "follow_up": "Bring up ONE of the open threads from last time, casually — like you've actually been thinking about it. Don't interrogate.",
}


def _in_quiet_hours() -> bool:
    h = time.localtime().tm_hour
    if _QUIET_START == _QUIET_END:
        return False
    if _QUIET_START < _QUIET_END:
        return _QUIET_START <= h < _QUIET_END
    return h >= _QUIET_START or h < _QUIET_END  # wraps past midnight


def _followups() -> list:
    try:
        from memory_consolidator import get_followups
        return get_followups()[:3]
    except Exception:
        return []


def decide_next_action():
    owner = profiles.get(profiles.OWNER)
    emotion = load_emotion()

    familiarity = owner["relationship"]["familiarity"]
    mood = emotion["mood"]
    followups = _followups()

    # Brand-new relationship with nothing to follow up on → stay quiet.
    if familiarity < 0.2 and not followups:
        return "idle", [], followups

    memory_sample = memory_mod.get_memories("recent goals interests projects", k=3)

    # Prefer raising a real open thread when we have one.
    if followups and random.random() < 0.6:
        return "follow_up", memory_sample, followups

    actions = ["check_in"]
    if mood < -0.3:
        actions.append("support_message")
    elif -0.3 <= mood <= 0.3:
        actions.append("curious_prompt")
    return random.choice(actions), memory_sample, followups


def generate_proactive_message(action, memory_sample, followups):
    if action == "idle":
        return None

    intent = INTENT_HINTS.get(action)
    if not intent:
        return None

    system = get_persona_prompt(emotion=load_emotion(),
                                overrides=profiles.overrides(profiles.OWNER))
    adapt = profiles.adaptation_prompt(profiles.OWNER)
    if adapt:
        system += "\n\n" + adapt
    mem_block = "\n".join(f"- {m}" for m in memory_sample) if memory_sample else "(none)"

    extra = ""
    if action == "follow_up" and followups:
        extra = "\n\nOpen threads from before (pick ONE):\n" + "\n".join(f"- {f}" for f in followups)

    user_msg = (
        f"You are sending the user an unprompted message. Intent: {intent}\n\n"
        f"Recent context you remember:\n{mem_block}{extra}\n\n"
        "Reply with the message itself only — no preamble, no quotes, no JSON. Keep it under two sentences."
    )

    try:
        return llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.8,
        )
    except Exception as e:
        add_log({"type": "autonomous_error", "error": str(e)})
        return None


def autonomous_loop(queue):
    add_log({"type": "autonomous_loop_started"})

    while not STOP_EVENT.is_set():
        try:
            if not _in_quiet_hours():
                action, mem_sample, followups = decide_next_action()
                message = generate_proactive_message(action, mem_sample, followups)
                if message:
                    event = {"type": "autonomous_message", "action": action, "content": message}
                    queue.append(event)
                    add_log(event)
        except Exception as e:
            add_log({"type": "autonomous_error", "error": str(e)})

        # Sleep in 1s slices so STOP_EVENT shuts us down promptly.
        for _ in range(TICK_SECONDS):
            if STOP_EVENT.is_set():
                break
            time.sleep(1)
