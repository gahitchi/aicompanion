import threading

from cognition_loop import cognition_cycle
from swarm.coordinator import start_swarm

from shared_state import push

task_queue = []


def execute_task(task):

    return f"executed: {task}"


if __name__ == "__main__":

    print("RESEARCH AGENT SYSTEM ONLINE")

    # SWARM
    start_swarm(task_queue, n=4)

    # COGNITION LOOP
    threading.Thread(
        target=cognition_cycle,
        args=(task_queue,),
        daemon=True
    ).start()

    while True:

        cmd = input("> ")

        push(cmd)

        task_queue.append(cmd)