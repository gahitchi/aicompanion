"""Unified FastAPI server for the Companion.

Merges what used to live in api/main.py, api/gateway.py, ui/server.py, ui/dashboard.py.
Serves the static dashboard from ui/static and exposes REST + WebSocket endpoints.
"""
import envconfig  # noqa: F401  — load .env before any module reads os.environ
import asyncio
import json
import os
import time

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
    # Fold typed chat into the same event stream the voice loop uses, so the
    # dashboard's sphere + history react to it exactly like spoken turns.
    events.publish({"type": "heard", "text": req.text, "source": "text"})
    events.publish({"type": "status", "state": "thinking"})
    try:
        reply = companion.chat(req.text, lang=req.lang)
    except Exception as e:
        events.publish({"type": "status", "state": "idle"})
        return JSONResponse({"error": str(e)}, status_code=500)
    events.publish({"type": "said", "text": reply})
    events.publish({"type": "status", "state": "idle"})
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


def _humanize_in(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"in {seconds}s"
    if seconds < 3600:
        return f"in {seconds // 60} min"
    if seconds < 86400:
        return f"in {seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"in {seconds // 86400}d"


@app.get("/overview")
def overview():
    """Aggregate live state for the dashboard panels. Every section is guarded so
    a missing/unconfigured feature degrades to empty rather than failing the call."""
    out = {"emotion": {}, "relationship": {}, "timers": [], "reminders": [],
           "flashcards_due": 0, "spending": None, "calendar": None}
    now = time.time()
    try:
        out["emotion"] = load_emotion()
    except Exception:
        pass
    try:
        out["relationship"] = load_identity().get("relationship_state", {})
    except Exception:
        pass
    try:
        import scheduler
        out["timers"] = [{"label": t.get("message", "timer"),
                          "seconds_left": max(0, int(t["run_at"] - now))}
                         for t in scheduler.list_reminders(kind="timer")]
        out["reminders"] = [{"message": t.get("message", ""),
                             "in": _humanize_in(t["run_at"] - now)}
                            for t in scheduler.list_reminders(kind="reminder")[:5]]
    except Exception:
        pass
    try:
        from tools import flashcards
        out["flashcards_due"] = len(flashcards._due_cards(flashcards._load()))
    except Exception:
        pass
    try:
        from tools import expenses
        data = expenses._load()
        start = expenses._period_start("week")
        total = round(sum(e["amount"] for e in data["log"]
                          if expenses._in_period(e["date"], start)), 2)
        out["spending"] = {"total": total, "currency": expenses._currency(),
                           "period": "week"}
    except Exception:
        pass
    try:
        from tools import gcal
        if gcal._service() is not None:
            out["calendar"] = gcal.list_events("today")
    except Exception:
        pass
    return out


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
