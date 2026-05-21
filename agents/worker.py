import time
from shared_state import pop_task, add_log


def worker_loop(run_task_fn):

    print("[WORKER] started")

    while True:

        task = pop_task()

        if task:

            try:
                result = run_task_fn(task)

                add_log({
                    "type": "worker_done",
                    "task": task,
                    "result": result
                })

            except Exception as e:

                add_log({
                    "type": "worker_error",
                    "task": task,
                    "error": str(e)
                })

        time.sleep(1)