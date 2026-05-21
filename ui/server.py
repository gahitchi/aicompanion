from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from shared_state import get_state, push_task

import asyncio

app = FastAPI()

clients = []


app.mount("/", StaticFiles(directory="ui/static", html=True), name="static")


@app.websocket("/ws")
async def ws(websocket: WebSocket):

    await websocket.accept()
    clients.append(websocket)

    try:
        while True:

            data = await websocket.receive_text()

            push_task(data)

            await broadcast({
                "type": "task_injected",
                "task": data
            })

    except:
        clients.remove(websocket)


async def broadcast(msg):

    dead = []

    for c in clients:

        try:
            await c.send_json(msg)
        except:
            dead.append(c)

    for d in dead:
        clients.remove(d)


@app.get("/state")
def state():
    return get_state()


@app.get("/graph")
def graph():

    state = get_state()

    # simple clustering visualization structure
    nodes = []
    edges = []

    for i, log in enumerate(state["logs"]):

        nodes.append({
            "id": i,
            "label": log.get("type", "event")
        })

        if i > 0:
            edges.append({"from": i-1, "to": i})

    return {"nodes": nodes, "edges": edges}