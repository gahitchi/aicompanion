import json
import os

FILE = "episodes.json"


def load():

    if not os.path.exists(FILE):
        return []

    return json.loads(open(FILE, "r").read())


def save(data):

    with open(FILE, "w") as f:
        f.write(json.dumps(data, indent=2))


def add_episode(user, ai, emotion):

    data = load()

    summary = {
        "user": user,
        "ai": ai,
        "emotion": emotion
    }

    data.append(summary)

    # keep only last 50 episodes
    data = data[-50:]

    save(data)


def retrieve_recent():

    return load()[-5:]