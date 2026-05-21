from services.model_router import ModelRouter
from runtime.tool_runtime import execute
from memory.vector_db import search

router = ModelRouter()


def run_task(task):

    context = search(task)

    model = router.select("smart")

    decision = {
        "task": task,
        "context": context,
        "model": model
    }

    # simplified execution flow
    result = f"executed({task}) using {model}"

    return result