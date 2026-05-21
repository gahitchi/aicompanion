import random
import json
import os

FILE = "policy.json"


def load():

    if not os.path.exists(FILE):
        return {}

    return json.loads(open(FILE, "r").read())


def save(data):

    with open(FILE, "w") as f:
        f.write(json.dumps(data, indent=2))


def choose_action(state, actions):

    policy = load()

    if state not in policy:
        policy[state] = {a: 1.0 for a in actions}

    weights = policy[state]

    return max(actions, key=lambda a: weights.get(a, 1.0))


def update(state, action, reward):

    policy = load()

    if state not in policy:
        policy[state] = {}

    policy[state][action] = policy[state].get(action, 1.0) + 0.1 * reward

    save(policy)