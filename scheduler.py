import time
from datetime import datetime


TASKS = []


def add_task(task, delay_seconds):

    TASKS.append({
        "task": task,
        "run_at": time.time() + delay_seconds
    })


def get_due_tasks():

    now = time.time()

    due = [t for t in TASKS if t["run_at"] <= now]

    TASKS[:] = [t for t in TASKS if t["run_at"] > now]

    return due


def scheduler_loop(queue):

    while True:

        due = get_due_tasks()

        for task in due:
            queue.append(task["task"])

        time.sleep(1)