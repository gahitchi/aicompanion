"""Unified FastAPI server for the Companion.

Merges what used to live in api/main.py, api/gateway.py, ui/server.py, ui/dashboard.py.
Serves the static dashboard from ui/static and exposes REST + WebSocket endpoints.
"""
import asyncio
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import events
import memory
from core.agent import Companion
from emotion import load as load_emotion
from identity import load as load_identity
from shared_state import get_state, push_task


app = FastAPI(title="Companion")
companion = Companion()

GOALS_FILE = "goals.json"


class ChatRequest(BaseModel):
    text: str
    lang: str | None = None  # ISO short code; voice loop normally fills this in


@app.post("/chat")
def chat(req: ChatRequest):
    reply = companion.chat(req.text, lang=req.lang)
    return {"reply": reply}


class TaskRequest(BaseModel):
    task: str


@app.post("/task")
def task(req: TaskRequest):
    result = companion.run_task(req.task)
    return {"result": result}


@app.get("/state")
def state():
    return {
        "queue_logs": get_state(),
        "emotion": load_emotion(),
        "identity": load_identity(),
    }


@app.get("/memory")
def get_memory(q: str = "recent", k: int = 10):
    return {"query": q, "results": memory.get_memories(q, k=k)}


@app.get("/goals")
def goals():
    if not os.path.exists(GOALS_FILE):
        return []
    try:
        return json.loads(open(GOALS_FILE).read())
    except json.JSONDecodeError:
        return []


@app.get("/graph")
def graph():
    s = get_state()
    nodes, edges = [], []
    for i, ev in enumerate(s["logs"]):
        nodes.append({"id": i, "label": ev.get("type", "event") if isinstance(ev, dict) else str(ev)[:30]})
        if i > 0:
            edges.append({"from": i - 1, "to": i})
    return {"nodes": nodes, "edges": edges}


clients: list[WebSocket] = []


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    try:
        while True:
            text = await websocket.receive_text()
            reply = await asyncio.to_thread(companion.chat, text)
            await websocket.send_json({"type": "reply", "user": text, "ai": reply})
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in clients:
            clients.remove(websocket)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/events/recent")
def events_recent(limit: int = 50):
    """Snapshot for initial page load. The WS connection takes over after."""
    return {"events": events.recent(limit=limit)}


@app.websocket("/events/ws")
async def events_ws(websocket: WebSocket):
    """Stream live events to the dashboard. Each message is one event dict."""
    await websocket.accept()
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _push(ev: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ev)

    events.subscribe(_push)
    try:
        # Initial hydration so a freshly-opened tab has recent context.
        for ev in events.recent(limit=30):
            await websocket.send_json(ev)
        while True:
            ev = await queue.get()
            await websocket.send_json(ev)
    except WebSocketDisconnect:
        pass
    finally:
        events.unsubscribe(_push)


# Static dashboard last so it doesn't shadow API routes
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "ui", "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
