import json
import os

FILE = "rewards.json"


def load():

    if not os.path.exists(FILE):
        return {}

    return json.loads(open(FILE, "r").read())


def save(data):

    with open(FILE, "w") as f:
        f.write(json.dumps(data, indent=2))


def reward(task, score):

    data = load()

    if task not in data:
        data[task] = []

    data[task].append(score)

    save(data)


def get_policy_score(task):

    data = load().get(task, [])

    if not data:
        return 0

    return sum(data) / len(data)