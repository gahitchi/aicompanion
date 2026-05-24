"""Process-local shared state: task queue + log ring. Used by autonomous loop, scheduler, UI."""
import threading
from collections import deque

STATE = {
    "queue": deque(),
    "logs": [],
}

# Set by the tray (or any module) to ask the main thread to exit cleanly.
# The launcher's tk loop polls this and calls root.quit() when set.
STOP_EVENT = threading.Event()

# Set while TTS is playing audio. The ASR callback drops input frames while
# this is set, so the Companion doesn't transcribe its own voice and loop.
SPEAKING = threading.Event()

# Set by the ASR loop when the user starts talking over Jade (barge-in). TTS
# watches this and stops speaking; it's cleared at the start of the next reply.
INTERRUPT = threading.Event()

# Wall-clock time of the last user utterance (set by the voice controller).
# The proactive speaker uses it to avoid talking right after the user did.
LAST_USER_SPEECH = 0.0


def push(task):
    STATE["queue"].append(task)


def pop():
    if STATE["queue"]:
        return STATE["queue"].popleft()
    return None


def log(event):
    STATE["logs"].append(event)
    STATE["logs"] = STATE["logs"][-200:]


def get_state():
    return {
        "queue": list(STATE["queue"]),
        "logs": STATE["logs"],
    }


push_task = push
pop_task = pop
add_log = log
