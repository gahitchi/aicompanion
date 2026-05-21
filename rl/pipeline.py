import json

DATASET = "rl_data.json"


def log_interaction(task, result, reward):

    try:
        data = json.loads(open(DATASET).read())
    except:
        data = []

    data.append({
        "task": task,
        "result": result,
        "reward": reward
    })

    with open(DATASET, "w") as f:
        f.write(json.dumps(data, indent=2))


def compute_reward(result):

    score = 0

    if len(result) > 50:
        score += 1

    if "error" in result:
        score -= 2

    return score