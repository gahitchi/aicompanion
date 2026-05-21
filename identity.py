import json
import os

FILE = "identity_memory.json"


DEFAULT = {
    "user_profile": {
        "interests": [],
        "communication_style": "unknown",
        "technical_level": "unknown"
    },
    "relationship_state": {
        "familiarity": 0.0,   # grows over time
        "trust": 0.0,
        "interaction_count": 0
    },
    "long_term_goals": []
}


def load():

    if not os.path.exists(FILE):
        save(DEFAULT)
        return DEFAULT

    return json.loads(open(FILE, "r").read())


def save(data):

    with open(FILE, "w") as f:
        f.write(json.dumps(data, indent=2))


def update_from_interaction(user_text, ai_text):

    data = load()

    profile = data["user_profile"]
    rel = data["relationship_state"]

    text = user_text.lower()

    # -------------------------
    # INTEREST EXTRACTION
    # -------------------------

    interests = ["robotics", "cybersecurity", "ai", "programming", "linux"]

    for i in interests:
        if i in text and i not in profile["interests"]:
            profile["interests"].append(i)

    # -------------------------
    # TECH LEVEL ESTIMATION
    # -------------------------

    if any(x in text for x in ["explain", "what is"]):
        profile["technical_level"] = "beginner"

    if any(x in text for x in ["architecture", "optimize", "distributed"]):
        profile["technical_level"] = "intermediate"

    if any(x in text for x in ["rl", "gnn", "vector db", "agent system"]):
        profile["technical_level"] = "advanced"

    # -------------------------
    # RELATIONSHIP EVOLUTION
    # -------------------------

    rel["interaction_count"] += 1
    rel["familiarity"] += 0.02

    if "thanks" in text or "good" in text:
        rel["trust"] += 0.03

    if "stupid" in text or "bad" in text:
        rel["trust"] -= 0.05

    # clamp values
    rel["familiarity"] = max(0, min(1, rel["familiarity"]))
    rel["trust"] = max(-1, min(1, rel["trust"]))

    # -------------------------
    # LONG TERM GOAL INFERENCE
    # -------------------------

    if "build" in text and "ai" in text:
        if "build ai system" not in data["long_term_goals"]:
            data["long_term_goals"].append("build ai system")

    if "robotics" in text:
        if "robotics project" not in data["long_term_goals"]:
            data["long_term_goals"].append("robotics project")

    save(data)


def get_identity_prompt():

    data = load()

    profile = data["user_profile"]
    rel = data["relationship_state"]

    return f"""
Long-term user model:

Interests: {', '.join(profile['interests'])}
Technical level: {profile['technical_level']}

Relationship:
- familiarity: {rel['familiarity']}
- trust: {rel['trust']}
- interactions: {rel['interaction_count']}

Long-term inferred goals:
{', '.join(data['long_term_goals'])}
"""