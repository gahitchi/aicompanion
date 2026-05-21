import json
import os

FILE = "user.json"


def load_user():

    if not os.path.exists(FILE):
        return {"interests": [], "style_pref": "neutral"}

    return json.loads(open(FILE, "r").read())


def update_user(text):

    data = load_user()

    text_lower = text.lower()

    if "robotics" in text_lower:
        if "robotics" not in data["interests"]:
            data["interests"].append("robotics")

    if "cybersecurity" in text_lower:
        if "cybersecurity" not in data["interests"]:
            data["interests"].append("cybersecurity")

    with open(FILE, "w") as f:
        f.write(json.dumps(data, indent=2))


def build_user_context():

    u = load_user()

    return f"User interests: {', '.join(u.get('interests', []))}"