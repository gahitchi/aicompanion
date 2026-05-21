from swarm.worker import worker
import threading


def start_swarm(queue, n=3):

    for i in range(n):

        threading.Thread(
            target=worker,
            args=(i, queue),
            daemon=True
        ).start()