"""Proactive autonomous loop. Decides when to speak unprompted based on the
relationship + emotional state, then generates an in-character message via the LLM."""
import random
import time

import llm
import memory as memory_mod
from emotion import load as load_emotion
from identity import load as load_identity
from persona import get_persona_prompt
from shared_state import add_log


TICK_SECONDS = 120


INTENT_HINTS = {
    "check_in": "Briefly check in with the user about what they were working on. Don't be saccharine.",
    "support_message": "The user's mood seems low. Offer a short, low-pressure opening to talk. Don't be performative.",
    "curious_prompt": "Ask one open, genuinely curious question about a project or interest the user has mentioned.",
}


def decide_next_action():
    identity = load_identity()
    emotion = load_emotion()

    familiarity = identity["relationship_state"]["familiarity"]
    mood = emotion["mood"]

    actions = []
    if familiarity < 0.2:
        actions.append("idle")
    else:
        actions.append("check_in")

    if mood < -0.3:
        actions.append("support_message")
    elif -0.3 <= mood <= 0.3:
        actions.append("curious_prompt")

    memory_sample = memory_mod.get_memories("recent goals interests projects", k=3)

    return random.choice(actions), memory_sample


def generate_proactive_message(action, memory_sample):
    if action == "idle":
        return None

    intent = INTENT_HINTS.get(action)
    if not intent:
        return None

    system = get_persona_prompt(emotion=load_emotion(), identity=load_identity())
    mem_block = "\n".join(f"- {m}" for m in memory_sample) if memory_sample else "(none)"

    user_msg = (
        f"You are sending the user an unprompted message. Intent: {intent}\n\n"
        f"Recent context you remember:\n{mem_block}\n\n"
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

    while True:
        try:
            action, mem_sample = decide_next_action()
            message = generate_proactive_message(action, mem_sample)

            if message:
                event = {"type": "autonomous_message", "action": action, "content": message}
                queue.append(event)
                add_log(event)
        except Exception as e:
            add_log({"type": "autonomous_error", "error": str(e)})

        time.sleep(TICK_SECONDS)
