import time
from core.broker import pop_task
from memory.vector_db import store_vector
from memory.graph_db import add_relation


def process(task):

    result = f"processed: {task}"

    # store structured memory
    store_vector(str(task))
    add_relation(task, result, "produced")

    return result


def run_worker(worker_id):

    print(f"[WORKER {worker_id}] started")

    while True:

        task = pop_task()

        if task:

            result = process(task)

            print(f"[WORKER {worker_id}] {result}")

        time.sleep(0.2)