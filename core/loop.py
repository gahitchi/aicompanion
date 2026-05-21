import time
from shared_state import pop, log

from agents.planner import run as planner
from agents.executor import run as executor
from agents.critic import evaluate

from memory.hybrid_memory import retrieve_context
from rl.reward import reward


def start_loop(run_task_fn):

    print("[CORE LOOP] started")

    while True:

        task = pop()

        if task:

            log({"type": "task_start", "task": task})

            context = retrieve_context(task)

            plan = planner(task, context)

            result = executor(plan)

            critique = evaluate(task, result)

            reward(task, critique["score"])

            log({
                "task": task,
                "result": result,
                "score": critique["score"]
            })

        time.sleep(1)