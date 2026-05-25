"""Tool registry with safety-tier awareness, JSON-Schema export, and audit log.

Each entry: (function, json_schema). The function returns either a string
result (executed) or a `_Result` sentinel with tier=CONFIRM (waiting for the
user's yes/no). The registry doesn't re-decide tier — it trusts the function
because tools that depend on args (run_command, fs ops) need per-call decisions.

`run(name, **kwargs)` is the safe call path. `run(name, _confirmed=True, ...)`
re-runs with the safety bypass active — used by the agent after the user
confirms a pending action.

Every call (and its outcome) is appended to ~/.aicompanion/audit.log as JSONL.
"""
import datetime
import json
import os
from pathlib import Path

import events
from tools.apps import open_app, open_url
from tools.filesystem import (
    _Result, append_file, copy, delete_dir, delete_file, find_files,
    list_dir, mkdir, move, read_file, write_file,
)
from tools.media import (
    media_next, media_pause, media_play, media_play_pause, media_prev,
    media_set_volume, media_status,
)
from tools.python_exec import python_exec
from tools.gcal import cancel_event, create_event, list_events
from tools.mail import list_inbox, read_email, send_email
from tools.reminders import cancel_reminder, list_reminders, set_reminder
from tools.runner import run_command
from tools.safety import bypass
from tools.system import battery_status, current_time, notify, screenshot
from tools.vision import look_at_image, see_screen
from tools.web import fetch_url, search_web
from tools.weather import get_weather
from tools.news import get_headlines
from tools.timers import cancel_timer, list_timers, start_timer
from tools.summarize import summarize
from tools.lists import add_to_list, remove_from_list, show_list
from tools.briefing import daily_briefing
from tools.spotify import spotify_now_playing, spotify_pause, spotify_play
import memory


# ---------- audit log ------------------------------------------------------

AUDIT_DIR = Path.home() / ".aicompanion"
AUDIT_LOG = AUDIT_DIR / "audit.log"


def _audit(event: dict) -> None:
    """Append a JSONL record AND publish to the dashboard event bus.
    Failures here must never break the tool path."""
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        event["t"] = datetime.datetime.now().isoformat(timespec="seconds")
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception:
        pass
    try:
        events.publish({"type": "tool", **event})
    except Exception:
        pass


# ---------- memory helpers (existing tools) --------------------------------

def _recall(query: str, k: int = 5):
    """Hybrid retrieval: semantic top-k + recent episodes + matching summaries.

    The plain semantic search misses two important cases:
      - Very recent context the user means by "what did I JUST say about X"
      - Long-term consolidated summaries (kind="summary") that capture themes
        an episodic match would dilute.
    """
    semantic = memory.get_memories(query, k=k)

    # Recency: scan the last few episodes for keyword overlap with the query.
    recent_hits = []
    try:
        from episodic_memory import load as load_episodes
        words = {w for w in query.lower().split() if len(w) > 3}
        for ep in load_episodes()[-15:]:
            joined = ((ep.get("user") or "") + " " + (ep.get("ai") or "")).lower()
            if words and any(w in joined for w in words):
                recent_hits.append(f"recent — user: {ep.get('user', '')[:100]} / jade: {ep.get('ai', '')[:100]}")
    except Exception:
        pass

    # Dedupe while preserving order. Summaries are already in semantic via Chroma.
    seen = set()
    out = []
    for line in semantic + recent_hits:
        key = line.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return "\n".join(out) or "(no memories)"


def _remember(text: str, kind: str = "event"):
    memory.save_memory(text, kind=kind)
    return "ok"


# ---------- registry -------------------------------------------------------
# Schema dicts follow OpenAI/Ollama tool format. Keep descriptions short and
# concrete — the LLM uses these to decide when to call.

TOOLS = {
    # ---- filesystem ------------------------------------------------------
    "read_file": {
        "fn": read_file,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the contents of a text file. Paths in ~ or /tmp are safe; outside requires confirmation.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "Path to the file (~ allowed)."}},
                    "required": ["path"],
                },
            },
        },
    },
    "write_file": {
        "fn": write_file,
        "schema": {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file, overwriting if it exists. Always confirms.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
    },
    "append_file": {
        "fn": append_file,
        "schema": {
            "type": "function",
            "function": {
                "name": "append_file",
                "description": "Append content to the end of a file. Confirms.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
    },
    "list_dir": {
        "fn": list_dir,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "List the files in a directory. Use when asked 'what's in my Downloads', 'show me my Desktop', etc. Defaults to ~ if no path given.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "default": "~"}},
                },
            },
        },
    },
    "mkdir": {
        "fn": mkdir,
        "schema": {
            "type": "function",
            "function": {
                "name": "mkdir",
                "description": "Create a directory (and any parents).",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
    },
    "delete_file": {
        "fn": delete_file,
        "schema": {
            "type": "function",
            "function": {
                "name": "delete_file",
                "description": "Delete a single file. Confirms.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
    },
    "delete_dir": {
        "fn": delete_dir,
        "schema": {
            "type": "function",
            "function": {
                "name": "delete_dir",
                "description": "Delete a directory. Pass recursive=true to remove contents too. Confirms.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "recursive": {"type": "boolean", "default": False},
                    },
                    "required": ["path"],
                },
            },
        },
    },
    "move": {
        "fn": move,
        "schema": {
            "type": "function",
            "function": {
                "name": "move",
                "description": "Move or rename a file or directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string"},
                        "dst": {"type": "string"},
                    },
                    "required": ["src", "dst"],
                },
            },
        },
    },
    "copy": {
        "fn": copy,
        "schema": {
            "type": "function",
            "function": {
                "name": "copy",
                "description": "Copy a file or directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string"},
                        "dst": {"type": "string"},
                    },
                    "required": ["src", "dst"],
                },
            },
        },
    },
    "find_files": {
        "fn": find_files,
        "schema": {
            "type": "function",
            "function": {
                "name": "find_files",
                "description": "Find files matching a glob pattern under a directory. Example pattern: '*.pdf'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "pattern": {"type": "string"},
                    },
                    "required": ["path", "pattern"],
                },
            },
        },
    },

    # ---- shell -----------------------------------------------------------
    "run_command": {
        "fn": run_command,
        "schema": {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Run a shell command. Read-only / info commands run immediately; modifying or unknown commands confirm; dangerous ones are denied.",
                "parameters": {
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}},
                    "required": ["cmd"],
                },
            },
        },
    },

    # ---- web -------------------------------------------------------------
    "search_web": {
        "fn": search_web,
        "schema": {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Web search (DuckDuckGo). Use for 'search for X', 'look up Y', 'what's the latest on Z' — anything you don't already know.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
    },
    "fetch_url": {
        "fn": fetch_url,
        "schema": {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Fetch a URL and return the readable text content.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
    },

    # ---- apps & launchers ------------------------------------------------
    "open_url": {
        "fn": open_url,
        "schema": {
            "type": "function",
            "function": {
                "name": "open_url",
                "description": "Open a URL in the user's default browser.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
    },
    "open_app": {
        "fn": open_app,
        "schema": {
            "type": "function",
            "function": {
                "name": "open_app",
                "description": "Launch an application by name (Firefox, kate, code, spotify, etc.).",
                "parameters": {
                    "type": "object",
                    "properties": {"app": {"type": "string"}},
                    "required": ["app"],
                },
            },
        },
    },

    # ---- media (playerctl) -----------------------------------------------
    "media_play_pause": {
        "fn": media_play_pause,
        "schema": {
            "type": "function",
            "function": {"name": "media_play_pause",
                         "description": "Toggle play/pause on whatever's currently playing. Use for 'play something', 'pause', 'play that again', 'put music on'.",
                         "parameters": {"type": "object", "properties": {}}},
        },
    },
    "media_play": {
        "fn": media_play,
        "schema": {"type": "function", "function": {"name": "media_play",
                   "description": "Resume playback.",
                   "parameters": {"type": "object", "properties": {}}}},
    },
    "media_pause": {
        "fn": media_pause,
        "schema": {"type": "function", "function": {"name": "media_pause",
                   "description": "Pause playback.",
                   "parameters": {"type": "object", "properties": {}}}},
    },
    "media_next": {
        "fn": media_next,
        "schema": {"type": "function", "function": {"name": "media_next",
                   "description": "Skip to the next track.",
                   "parameters": {"type": "object", "properties": {}}}},
    },
    "media_prev": {
        "fn": media_prev,
        "schema": {"type": "function", "function": {"name": "media_prev",
                   "description": "Go back to the previous track.",
                   "parameters": {"type": "object", "properties": {}}}},
    },
    "media_status": {
        "fn": media_status,
        "schema": {"type": "function", "function": {"name": "media_status",
                   "description": "What's currently playing. Use for 'what song is this', 'what's playing', 'who's this'.",
                   "parameters": {"type": "object", "properties": {}}}},
    },
    "media_set_volume": {
        "fn": media_set_volume,
        "schema": {
            "type": "function",
            "function": {
                "name": "media_set_volume",
                "description": "Set the media player volume, 0-100.",
                "parameters": {
                    "type": "object",
                    "properties": {"percent": {"type": "integer"}},
                    "required": ["percent"],
                },
            },
        },
    },

    # ---- system ----------------------------------------------------------
    "current_time": {
        "fn": current_time,
        "schema": {"type": "function", "function": {"name": "current_time",
                   "description": "Current date and time. Use for 'what time is it', 'what day is it', 'how late is it'.",
                   "parameters": {"type": "object", "properties": {}}}},
    },
    "notify": {
        "fn": notify,
        "schema": {
            "type": "function",
            "function": {
                "name": "notify",
                "description": "Pop a desktop notification. Use for 'remind me about X', 'send me a note', or to flag something visually.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string", "default": ""},
                    },
                    "required": ["title"],
                },
            },
        },
    },
    "screenshot": {
        "fn": screenshot,
        "schema": {
            "type": "function",
            "function": {
                "name": "screenshot",
                "description": "Take a fullscreen screenshot. Saves to ~/Pictures/Screenshots if path is empty.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "default": ""}},
                },
            },
        },
    },
    "battery_status": {
        "fn": battery_status,
        "schema": {"type": "function", "function": {"name": "battery_status",
                   "description": "Battery level + charging state. Use for 'how much battery', 'am I charging', 'how long do I have'.",
                   "parameters": {"type": "object", "properties": {}}}},
    },

    # ---- python ----------------------------------------------------------
    "python_exec": {
        "fn": python_exec,
        "schema": {
            "type": "function",
            "function": {
                "name": "python_exec",
                "description": "Execute a snippet of Python in a fresh subprocess. Always confirms.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "timeout": {"type": "integer", "default": 10},
                    },
                    "required": ["code"],
                },
            },
        },
    },

    # ---- memory ----------------------------------------------------------
    "recall": {
        "fn": _recall,
        "schema": {
            "type": "function",
            "function": {
                "name": "recall",
                "description": "Search past conversation memory. Use for 'do you remember', 'what did I say about X', 'we talked about this before'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "k": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        },
    },
    "remember": {
        "fn": _remember,
        "schema": {
            "type": "function",
            "function": {
                "name": "remember",
                "description": "Save a fact for future recall. Use when user explicitly says 'remember that', 'don't forget', 'note this down'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "kind": {"type": "string", "default": "event"},
                    },
                    "required": ["text"],
                },
            },
        },
    },
    # ---- vision ----------------------------------------------------------
    "see_screen": {
        "fn": see_screen,
        "schema": {
            "type": "function",
            "function": {
                "name": "see_screen",
                "description": "Look at the user's screen and describe it or answer a question about it. Use for 'what's on my screen', 'what am I looking at', 'read this for me', 'help me with what's here'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "Optional specific question about the screen."},
                    },
                },
            },
        },
    },
    "look_at_image": {
        "fn": look_at_image,
        "schema": {
            "type": "function",
            "function": {
                "name": "look_at_image",
                "description": "Look at an image file on disk and describe it or answer a question about it. Use when the user points to a picture/photo/screenshot by path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the image (~ allowed)."},
                        "question": {"type": "string", "description": "Optional specific question about the image."},
                    },
                    "required": ["path"],
                },
            },
        },
    },
    # ---- reminders -------------------------------------------------------
    "set_reminder": {
        "fn": set_reminder,
        "schema": {
            "type": "function",
            "function": {
                "name": "set_reminder",
                "description": "Set a spoken reminder for later. Use for 'remind me in 20 minutes to X', 'remind me at 6pm to Y'. Convert the time to in_seconds (relative) OR at_time ('HH:MM' or ISO). Put only the thing to do in message.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "What to remind them about (the action only)."},
                        "in_seconds": {"type": "integer", "description": "Fire this many seconds from now (e.g. 20 min = 1200)."},
                        "at_time": {"type": "string", "description": "Clock time 'HH:MM' (next occurrence) or ISO datetime."},
                    },
                    "required": ["message"],
                },
            },
        },
    },
    "list_reminders": {
        "fn": list_reminders,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_reminders",
                "description": "List the user's pending reminders. Use for 'what are my reminders', 'what did I ask you to remind me about'.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    },
    "cancel_reminder": {
        "fn": cancel_reminder,
        "schema": {
            "type": "function",
            "function": {
                "name": "cancel_reminder",
                "description": "Cancel a pending reminder by its id (get ids from list_reminders).",
                "parameters": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            },
        },
    },

    # ---- email (owner-only) ----------------------------------------------
    "list_inbox": {
        "fn": list_inbox,
        "owner_only": True,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_inbox",
                "description": "Summarize recent emails. Use for 'check my email', 'any new mail', 'what's in my inbox'. Defaults to unread, newest first.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer", "default": 5, "description": "How many to list."},
                        "unread_only": {"type": "boolean", "default": True},
                    },
                },
            },
        },
    },
    "read_email": {
        "fn": read_email,
        "owner_only": True,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_email",
                "description": "Read one email's full text by its id (ids come from list_inbox). Use for 'read me that email', 'what does it say'.",
                "parameters": {
                    "type": "object",
                    "properties": {"id": {"type": "string", "description": "Message id from list_inbox."}},
                    "required": ["id"],
                },
            },
        },
    },
    "send_email": {
        "fn": send_email,
        "owner_only": True,
        "schema": {
            "type": "function",
            "function": {
                "name": "send_email",
                "description": "Send an email. Use for 'email X', 'send a message to Y', 'reply to them'. Always confirms before sending.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient email address."},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
        },
    },

    # ---- calendar (owner-only) -------------------------------------------
    "list_events": {
        "fn": list_events,
        "owner_only": True,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_events",
                "description": "List calendar events. Use for 'what's on my calendar', 'am I free today', 'what's my schedule'. when='today' (default), 'week', or an ISO date.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "when": {"type": "string", "default": "today", "description": "'today', 'week', or an ISO date/datetime."},
                    },
                },
            },
        },
    },
    "create_event": {
        "fn": create_event,
        "owner_only": True,
        "schema": {
            "type": "function",
            "function": {
                "name": "create_event",
                "description": "Add a calendar event. Use for 'add X to my calendar', 'schedule Y', 'book Z'. Convert the time to an ISO datetime for start (and end if given). Always confirms.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start": {"type": "string", "description": "ISO datetime, e.g. 2026-05-25T12:00."},
                        "end": {"type": "string", "description": "ISO datetime; defaults to 1h after start."},
                        "description": {"type": "string", "default": ""},
                    },
                    "required": ["title", "start"],
                },
            },
        },
    },
    "cancel_event": {
        "fn": cancel_event,
        "owner_only": True,
        "schema": {
            "type": "function",
            "function": {
                "name": "cancel_event",
                "description": "Cancel a calendar event by its id (ids come from list_events). Always confirms.",
                "parameters": {
                    "type": "object",
                    "properties": {"event_id": {"type": "string"}},
                    "required": ["event_id"],
                },
            },
        },
    },

    # ---- weather / news --------------------------------------------------
    "get_weather": {
        "fn": get_weather,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Current weather or short forecast. Use for 'what's the weather', 'will it rain', 'how cold is it'. when='now' (default), 'today', 'tomorrow', or 'week'. location optional (defaults to the configured home).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name or 'lat,lon'. Omit for the default."},
                        "when": {"type": "string", "default": "now"},
                    },
                },
            },
        },
    },
    "get_headlines": {
        "fn": get_headlines,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_headlines",
                "description": "Top news headlines. Use for 'what's in the news', 'any headlines', 'what's going on in the world'. topic can be top/world/tech.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "default": "top"},
                        "n": {"type": "integer", "default": 5},
                    },
                },
            },
        },
    },

    # ---- timers ----------------------------------------------------------
    "start_timer": {
        "fn": start_timer,
        "schema": {
            "type": "function",
            "function": {
                "name": "start_timer",
                "description": "Start a countdown timer. Use for 'set a timer for 10 minutes', 'time 90 seconds'. Convert the duration to seconds; label is optional (e.g. 'pasta').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "seconds": {"type": "integer"},
                        "label": {"type": "string", "default": ""},
                    },
                    "required": ["seconds"],
                },
            },
        },
    },
    "list_timers": {
        "fn": list_timers,
        "schema": {"type": "function", "function": {"name": "list_timers",
                   "description": "List running timers and time left.",
                   "parameters": {"type": "object", "properties": {}}}},
    },
    "cancel_timer": {
        "fn": cancel_timer,
        "schema": {
            "type": "function",
            "function": {
                "name": "cancel_timer",
                "description": "Cancel a running timer by its id (from list_timers).",
                "parameters": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            },
        },
    },

    # ---- summarize -------------------------------------------------------
    "summarize": {
        "fn": summarize,
        "schema": {
            "type": "function",
            "function": {
                "name": "summarize",
                "description": "Summarize a web page, text file, or PDF. Use for 'summarize this article', 'what does this PDF say', 'tldr of <url>'. source is a URL or file path; question optionally focuses it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "description": "A URL or local file path."},
                        "question": {"type": "string", "default": ""},
                    },
                    "required": ["source"],
                },
            },
        },
    },

    # ---- spotify ---------------------------------------------------------
    "spotify_play": {
        "fn": spotify_play,
        "schema": {
            "type": "function",
            "function": {
                "name": "spotify_play",
                "description": "Play music on Spotify by name. Use for 'play Radiohead', 'put on my Discover Weekly', 'play some jazz'. Pass what to play as query; omit query to just resume. Prefer this over media_play_pause when the user names an artist/song/playlist.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "default": "", "description": "Track, artist, album, or playlist name. Omit to resume."},
                    },
                },
            },
        },
    },
    "spotify_pause": {
        "fn": spotify_pause,
        "schema": {"type": "function", "function": {"name": "spotify_pause",
                   "description": "Pause Spotify playback.",
                   "parameters": {"type": "object", "properties": {}}}},
    },
    "spotify_now_playing": {
        "fn": spotify_now_playing,
        "schema": {"type": "function", "function": {"name": "spotify_now_playing",
                   "description": "What's playing on Spotify right now (title + artist).",
                   "parameters": {"type": "object", "properties": {}}}},
    },

    # ---- briefing (owner-only) -------------------------------------------
    "daily_briefing": {
        "fn": daily_briefing,
        "owner_only": True,
        "schema": {
            "type": "function",
            "function": {
                "name": "daily_briefing",
                "description": "Give a short spoken morning briefing: weather, today's calendar, unread email, and a couple of headlines woven together. Use for 'give me my briefing', 'catch me up', 'what's my day look like'.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    },

    # ---- lists -----------------------------------------------------------
    "add_to_list": {
        "fn": add_to_list,
        "schema": {
            "type": "function",
            "function": {
                "name": "add_to_list",
                "description": "Add an item to a named list (shopping, to-do, etc.). Use for 'add milk to my shopping list', 'put X on my to-do'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "List name, e.g. 'shopping'."},
                        "item": {"type": "string"},
                    },
                    "required": ["name", "item"],
                },
            },
        },
    },
    "show_list": {
        "fn": show_list,
        "schema": {
            "type": "function",
            "function": {
                "name": "show_list",
                "description": "Show a named list, or all list names if none given. Use for 'what's on my shopping list', 'what lists do I have'.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "default": ""}},
                },
            },
        },
    },
    "remove_from_list": {
        "fn": remove_from_list,
        "schema": {
            "type": "function",
            "function": {
                "name": "remove_from_list",
                "description": "Remove an item from a named list. Use for 'take milk off my shopping list', 'remove X from my to-do'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "item": {"type": "string"},
                    },
                    "required": ["name", "item"],
                },
            },
        },
    },
}


def run(name: str, /, _confirmed: bool = False, owner: bool = True, **kwargs):
    """Execute a tool. Returns either a string (result) or a _Result(CONFIRM, ...)
    sentinel that the caller should resolve by asking the user.

    `name` is positional-only so a tool whose own argument is called "name"
    (e.g. add_to_list) doesn't collide with it.

    `owner` is the current speaker's owner status. Owner-only tools (email,
    calendar) are refused for non-owners as defense-in-depth — they're already
    withheld from the schema list by tool_schemas(owner=False), but a model that
    hallucinates the call still gets denied here."""
    entry = TOOLS.get(name)
    if entry is None:
        msg = f"tool_not_found: {name} (available: {sorted(TOOLS)})"
        _audit({"tool": name, "args": kwargs, "result": msg, "ok": False})
        return msg

    if entry.get("owner_only") and not owner:
        msg = (f"tool_denied: {name} is owner-only and the current speaker is "
               f"not the recognized owner.")
        _audit({"tool": name, "args": kwargs, "result": msg, "ok": False,
                "owner_only": True})
        return msg

    fn = entry["fn"]
    try:
        if _confirmed:
            with bypass():
                result = fn(**kwargs)
        else:
            result = fn(**kwargs)
    except TypeError as e:
        msg = f"tool_error: bad arguments to {name}: {e}"
        _audit({"tool": name, "args": kwargs, "result": msg, "ok": False,
                "confirmed": _confirmed})
        return msg
    except Exception as e:
        msg = f"tool_error: {name} raised {type(e).__name__}: {e}"
        _audit({"tool": name, "args": kwargs, "result": msg, "ok": False,
                "confirmed": _confirmed})
        return msg

    # Pending sentinel (CONFIRM tier, no bypass)
    if isinstance(result, _Result):
        _audit({"tool": name, "args": kwargs, "tier": result.tier,
                "result": "pending", "ok": True,
                "description": result.description})
        return result

    text = str(result)
    preview = text if len(text) <= 500 else text[:500] + "...(truncated)"
    _audit({"tool": name, "args": kwargs, "result": preview, "ok": True,
            "confirmed": _confirmed})
    return result


def tool_schemas(owner: bool = True) -> list:
    """JSON-schema list for the LLM's `tools=` parameter.

    When `owner` is False (the current speaker isn't the recognized owner),
    owner-only tools are withheld so a household member or guest is never even
    offered the owner's email/calendar."""
    return [entry["schema"] for entry in TOOLS.values()
            if owner or not entry.get("owner_only")]


def describe() -> list:
    """Compact (name, signature) pairs — used by the legacy ReAct prompt in run_task."""
    return [(name, entry["schema"]["function"]["description"]) for name, entry in TOOLS.items()]
