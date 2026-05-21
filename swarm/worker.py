import time
from tools.registry import run


def worker(node_id, queue):

    print(f"[SWARM NODE {node_id}] started")

    while True:

        if queue:

            task = queue.pop(0)

            result = run("execute_task", task)

            print(f"[NODE {node_id}] {result}")

        time.sleep(1)