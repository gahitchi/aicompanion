from prometheus_client import Counter

TASKS = Counter("tasks_total", "Total tasks processed")


def inc_task():

    TASKS.inc()