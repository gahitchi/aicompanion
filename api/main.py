from fastapi import FastAPI
from core.broker import push_task
from services.planner import plan

app = FastAPI()


@app.post("/task")
def create_task(task: str):

    plan(task)

    push_task({"type": "task", "content": task})

    return {"status": "queued"}


@app.get("/status")
def status():

    return {"system": "running"}