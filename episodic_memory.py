import json
import os

FILE = "episodes.json"

OWNER = "owner"
_MAX = 200  # global ring; retrieval filters per person


def load():

    if not os.path.exists(FILE):
        return []

    return json.loads(open(FILE, "r").read())


def save(data):

    with open(FILE, "w") as f:
        f.write(json.dumps(data, indent=2))


def add_episode(user, ai, emotion, person=OWNER):

    data = load()

    summary = {
        "user": user,
        "ai": ai,
        "emotion": emotion,
        "person": person or OWNER,
    }

    data.append(summary)

    # keep only the last _MAX episodes across everyone
    data = data[-_MAX:]

    save(data)


def _person_of(ep) -> str:
    # Episodes recorded before multi-user had no tag — treat them as the owner's.
    return ep.get("person", OWNER)


def retrieve_recent(person=OWNER, n=5):
    """Most recent `n` episodes for `person` (defaults to the owner)."""
    eps = [e for e in load() if _person_of(e) == person]
    return eps[-n:]


def by_person():
    """Group all episodes by person id → list of episodes (oldest-first)."""
    groups: dict = {}
    for e in load():
        groups.setdefault(_person_of(e), []).append(e)
    return groups
