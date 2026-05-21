from collections import deque

STATE = {
    "queue": deque(),
    "logs": []
}


def push(task):
    STATE["queue"].append(task)


def pop():

    if STATE["queue"]:
        return STATE["queue"].popleft()

    return None


def log(event):
    STATE["logs"].append(event)
    STATE["logs"] = STATE["logs"][-200:]