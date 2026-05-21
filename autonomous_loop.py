import time
import random
from identity import load as load_identity
from emotion import load as load_emotion
from memory import search


def decide_next_action():

    identity = load_identity()
    emotion = load_emotion()

    familiarity = identity["relationship_state"]["familiarity"]
    mood = emotion["mood"]

    memory_sample = search("recent goals interests")[0:3] if search else []

    # ----------------------------
    # SIMPLE POLICY ENGINE
    # ----------------------------

    actions = []

    # if user relationship is weak → stay quiet
    if familiarity < 0.2:
        actions.append("idle")

    # if user is active relationship → engage
    if familiarity >= 0.2:
        actions.append("check_in")

    # if mood is low → supportive behavior
    if mood < -0.3:
        actions.append("support_message")

    # if mood is neutral → curiosity behavior
    if -0.3 <= mood <= 0.3:
        actions.append("curious_prompt")

    # default fallback
    if not actions:
        actions.append("idle")

    return random.choice(actions), memory_sample


def generate_proactive_message(action, memory_sample):

    if action == "idle":
        return None

    if action == "check_in":
        return "I was thinking about what you were working on earlier."

    if action == "support_message":
        return "You seem a bit off recently. Want to talk about it?"

    if action == "curious_prompt":
        return "Have you made any progress on your current projects?"

    return None


def autonomous_loop(queue):

    while True:

        action, memory = decide_next_action()

        message = generate_proactive_message(action, memory)

        if message:
            queue.append({
                "type": "autonomous_message",
                "content": message
            })

        time.sleep(60)