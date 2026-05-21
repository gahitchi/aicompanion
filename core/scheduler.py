import json
import time
import uuid

GOALS_FILE = "goals.json"


def load_goals():

    try:
        return json.loads(open(GOALS_FILE, "r").read())
    except:
        return []


def save_goals(goals):

    with open(GOALS_FILE, "w") as f:
        f.write(json.dumps(goals, indent=2))


def add_goal(task, priority=5):

    goals = load_goals()

    goals.append({
        "id": str(uuid.uuid4()),
        "task": task,
        "priority": priority,
        "status": "pending"
    })

    save_goals(goals)


def get_next_goal():

    goals = load_goals()

    pending = [g for g in goals if g["status"] == "pending"]

    if not pending:
        return None

    pending.sort(key=lambda x: x["priority"], reverse=True)

    return pending[0]


def complete_goal(goal_id):

    goals = load_goals()

    for g in goals:
        if g["id"] == goal_id:
            g["status"] = "done"

    save_goals(goals)