import json
import os

FILE = "emotion.json"


DEFAULT = {
    "mood": 0.0,          # -1 (negative) → +1 (positive)
    "energy": 0.5,        # 0 → tired, 1 → active
    "curiosity": 0.5
}


def load():

    if not os.path.exists(FILE):
        save(DEFAULT)
        return DEFAULT

    return json.loads(open(FILE, "r").read())


def save(state):

    with open(FILE, "w") as f:
        f.write(json.dumps(state, indent=2))


def update_from_input(text):

    state = load()
    t = text.lower()

    # mood shifts
    if any(w in t for w in ["hate", "bad", "annoying", "stupid"]):
        state["mood"] -= 0.1

    if any(w in t for w in ["like", "love", "cool", "good"]):
        state["mood"] += 0.1

    # energy shifts
    if "?" in t:
        state["curiosity"] += 0.05

    state["mood"] = max(-1, min(1, state["mood"]))
    state["energy"] = max(0, min(1, state["energy"]))
    state["curiosity"] = max(0, min(1, state["curiosity"]))

    save(state)

    return state


def get_emotion_prompt():

    s = load()

    if s["mood"] > 0.3:
        tone = "slightly positive and engaged"
    elif s["mood"] < -0.3:
        tone = "slightly annoyed but controlled"
    else:
        tone = "neutral"

    return f"""
Emotional state:
- mood: {s['mood']}
- energy: {s['energy']}
- curiosity: {s['curiosity']}

Tone rule:
Respond in a {tone} manner.
"""