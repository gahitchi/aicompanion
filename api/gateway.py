from fastapi import FastAPI
from orchestrator.engine import run_task
from infra.bus import publish

app = FastAPI()


@app.post("/task")
def task_endpoint(task: str):

    result = run_task(task)

    publish({
        "task": task,
        "result": result
    })

    return {"status": "ok", "result": result}