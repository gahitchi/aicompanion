"""Google Calendar tools — list, create, and cancel events via the Calendar API.

Auth is OAuth (Google has no app-password path for Calendar). One-time setup:
create an OAuth *Desktop* client in Google Cloud, download its client-secret JSON
to JADE_GCAL_CLIENT_SECRET (default ~/.aicompanion/gcal_client_secret.json), then
run `jade --auth-calendar` once to grant access. The refresh token is cached at
~/.aicompanion/gcal_token.json and auto-refreshes, so the headless service never
needs the browser again.

list_events runs immediately (SAFE); create_event / cancel_event confirm first
(they mutate the calendar) by returning the CONFIRM sentinel. Registered
owner_only — withheld from / refused for non-owner speakers.

Fails open: a missing client secret or token returns a 'run jade --auth-calendar'
hint instead of raising. Module named `gcal` so it never shadows stdlib calendar
(which email.utils imports internally).
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.filesystem import _Result
from tools.safety import CONFIRM, bypass_enabled

SCOPES = ["https://www.googleapis.com/auth/calendar"]
_CONFIG_DIR = Path.home() / ".aicompanion"
TOKEN_PATH = _CONFIG_DIR / "gcal_token.json"


def _client_secret_path() -> Path:
    return Path(os.path.expanduser(os.environ.get(
        "JADE_GCAL_CLIENT_SECRET", str(_CONFIG_DIR / "gcal_client_secret.json"))))


def _calendar_id() -> str:
    return os.environ.get("JADE_GCAL_CALENDAR_ID", "primary")


def _setup_hint() -> str:
    return ("Calendar isn't connected yet. Put your Google OAuth client JSON at "
            f"{_client_secret_path()} and run `jade --auth-calendar` once.")


def _load_credentials():
    """Return refreshed Credentials, or None if not authorized / unusable."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if not TOKEN_PATH.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
    return creds if creds and creds.valid else None


def _service():
    """Build a Calendar API client, or None if not set up (never raises)."""
    try:
        creds = _load_credentials()
        if creds is None:
            return None
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        return None


def authorize() -> str:
    """One-time interactive OAuth flow — called by `jade --auth-calendar`."""
    secret = _client_secret_path()
    if not secret.exists():
        return (f"No OAuth client JSON at {secret}. In Google Cloud Console create "
                "an OAuth client of type 'Desktop app', download the JSON, save it "
                "there, then re-run `jade --auth-calendar`.")
    from google_auth_oauthlib.flow import InstalledAppFlow
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json())
    return f"Calendar connected — token saved to {TOKEN_PATH}."


def _fmt_event(ev) -> str:
    start = ev.get("start", {})
    when = start.get("dateTime", start.get("date", "?"))
    return f"- [{ev.get('id', '')}] {when} — {ev.get('summary', '(no title)')}"


def list_events(when: str = "today") -> str:
    """List upcoming events. `when` = 'today', 'week', or an ISO date/datetime
    lower bound. SAFE — read only."""
    svc = _service()
    if svc is None:
        return _setup_hint()
    try:
        now = datetime.now(timezone.utc)
        time_min = now
        if when == "week":
            time_max = now + timedelta(days=7)
        elif when and when not in ("today", ""):
            try:
                time_min = datetime.fromisoformat(when)
                if time_min.tzinfo is None:
                    time_min = time_min.astimezone()
            except ValueError:
                time_min = now
            time_max = time_min + timedelta(days=1)
        else:  # today
            time_max = now.astimezone().replace(hour=23, minute=59, second=59)
        events = svc.events().list(
            calendarId=_calendar_id(),
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=20,
        ).execute().get("items", [])
        if not events:
            return f"No events {when}."
        return f"Events ({when}):\n" + "\n".join(_fmt_event(e) for e in events)
    except Exception as e:
        return f"Calendar error: {type(e).__name__}: {e}"


def upcoming(within_min: int = 15) -> list:
    """Structured events starting within the next `within_min` minutes:
    [{'id', 'title', 'start'(aware datetime)}]. Empty on any error / not set up.
    All-day events are skipped (no precise start to nudge on). Used by nudge_loop."""
    svc = _service()
    if svc is None:
        return []
    try:
        now = datetime.now(timezone.utc)
        items = svc.events().list(
            calendarId=_calendar_id(),
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(minutes=within_min)).isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=10,
        ).execute().get("items", [])
        out = []
        for ev in items:
            dt = ev.get("start", {}).get("dateTime")
            if not dt:
                continue
            try:
                out.append({"id": ev.get("id"), "title": ev.get("summary", "(event)"),
                            "start": datetime.fromisoformat(dt)})
            except ValueError:
                continue
        return out
    except Exception:
        return []


def create_event(title: str, start: str, end: str = None, description: str = "") -> str:
    """Create an event. `start`/`end` are ISO datetimes (the model converts
    natural language → ISO, like set_reminder). CONFIRM."""
    svc = _service()
    if svc is None:
        return _setup_hint()
    if not bypass_enabled():
        return _Result(CONFIRM, f"add '{title}' to your calendar at {start}",
                       "create_event",
                       {"title": title, "start": start, "end": end,
                        "description": description})
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end) if end else start_dt + timedelta(hours=1)
    except ValueError:
        return "tool_error: start/end must be ISO, e.g. 2026-05-25T12:00."
    try:
        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
        }
        ev = svc.events().insert(calendarId=_calendar_id(), body=body).execute()
        return f"Added '{title}' ({ev.get('id')})."
    except Exception as e:
        return f"Calendar error: {type(e).__name__}: {e}"


def cancel_event(event_id: str) -> str:
    """Delete an event by id (ids come from list_events). CONFIRM."""
    svc = _service()
    if svc is None:
        return _setup_hint()
    if not bypass_enabled():
        return _Result(CONFIRM, f"cancel calendar event {event_id}",
                       "cancel_event", {"event_id": event_id})
    try:
        svc.events().delete(calendarId=_calendar_id(), eventId=event_id).execute()
        return f"Cancelled event {event_id}."
    except Exception as e:
        return f"Calendar error: {type(e).__name__}: {e}"


def _hhmm(s: str, default):
    try:
        h, m = s.strip().split(":")
        return int(h), int(m)
    except Exception:
        return default


def _slot_label(start) -> str:
    today = datetime.now().astimezone().date()
    d = start.date()
    if d == today:
        day = "today"
    elif d == today + timedelta(days=1):
        day = "tomorrow"
    else:
        day = start.strftime("%A")
    return day


def find_free_time(duration_min: int = 60, within: str = "week",
                   day_start: str = "09:00", day_end: str = "18:00") -> str:
    """Find free slots of at least duration_min within working hours over the
    next window ('today' or 'week'). Working hours default to 09:00-18:00 (or
    JADE_DAY_START/JADE_DAY_END). SAFE — read only. Only timed events count as
    busy; all-day events are ignored."""
    from datetime import time as dtime
    svc = _service()
    if svc is None:
        return _setup_hint()
    try:
        dur = timedelta(minutes=max(1, int(duration_min)))
    except (TypeError, ValueError):
        dur = timedelta(minutes=60)
    ds_h, ds_m = _hhmm(os.environ.get("JADE_DAY_START", day_start), (9, 0))
    de_h, de_m = _hhmm(os.environ.get("JADE_DAY_END", day_end), (18, 0))
    days = 1 if str(within).strip().lower() == "today" else 7

    now = datetime.now().astimezone()
    window_end = now + timedelta(days=days)
    try:
        events = svc.events().list(
            calendarId=_calendar_id(), timeMin=now.isoformat(),
            timeMax=window_end.isoformat(), singleEvents=True,
            orderBy="startTime", maxResults=100,
        ).execute().get("items", [])
    except Exception as e:
        return f"Calendar error: {type(e).__name__}: {e}"

    busy = []
    for ev in events:
        s = ev.get("start", {}).get("dateTime")
        e = ev.get("end", {}).get("dateTime")
        if not s or not e:
            continue  # skip all-day events
        try:
            busy.append((datetime.fromisoformat(s).astimezone(),
                         datetime.fromisoformat(e).astimezone()))
        except ValueError:
            continue

    slots = []
    for d in range(days):
        day = (now + timedelta(days=d)).date()
        ws = datetime.combine(day, dtime(ds_h, ds_m)).astimezone()
        we = datetime.combine(day, dtime(de_h, de_m)).astimezone()
        if d == 0:
            ws = max(ws, now)  # never suggest a time already past
        if ws >= we:
            continue
        day_busy = sorted((max(bs, ws), min(be, we)) for bs, be in busy if be > ws and bs < we)
        cursor = ws
        for bs, be in day_busy:
            if bs - cursor >= dur:
                slots.append((cursor, bs))
            cursor = max(cursor, be)
        if we - cursor >= dur:
            slots.append((cursor, we))
        if len(slots) >= 5:
            break

    if not slots:
        return (f"I don't see a free {int(duration_min)}-minute window "
                f"{'today' if days == 1 else 'this week'} during working hours.")
    lines = [f"{_slot_label(s)} {s.strftime('%H:%M')}–{e.strftime('%H:%M')}"
             for s, e in slots[:5]]
    return "You're free: " + "; ".join(lines) + "."
