"""Commute / travel-time — driving (and, with a key, transit) ETA between places.

Place names are geocoded with the shared no-key geocoder (tools/geo). Routing
uses the public OSRM demo server (router.project-osrm.org) by default: no key,
driving only, and **no live traffic**. If JADE_MAPS_API_KEY is set, Google
Directions is used instead, giving traffic-aware driving times and transit/
walking modes.

Saved places: "home" → JADE_HOME_LOCATION (falls back to JADE_WEATHER_LOCATION),
"work" → JADE_WORK_LOCATION; anything else is treated as a place name / address.
Both tools are SAFE (read only) and fail open with a short hint.
"""
import os
from datetime import datetime, timedelta

import requests

from tools.geo import geocode

_OSRM = "https://router.project-osrm.org/route/v1/driving"
_GOOGLE = "https://maps.googleapis.com/maps/api/directions/json"


def _place(name: str) -> str:
    """Resolve 'home'/'work'/'' to configured locations; pass anything else through."""
    n = (name or "").strip().lower()
    if n in ("", "home"):
        return os.environ.get("JADE_HOME_LOCATION") or os.environ.get("JADE_WEATHER_LOCATION") or ""
    if n == "work":
        return os.environ.get("JADE_WORK_LOCATION") or ""
    return name.strip()


def _route(origin: str, dest: str, mode: str):
    """Return ({duration_sec, distance_m, traffic, mode, dest_label}, None) or
    (None, error_message)."""
    key = os.environ.get("JADE_MAPS_API_KEY")
    mode = (mode or "driving").strip().lower()
    if key:
        return _route_google(origin, dest, mode, key)
    if mode != "driving":
        return None, ("Without a maps API key I can only estimate driving times. "
                      "Set JADE_MAPS_API_KEY in .env for transit, walking, and live traffic.")
    return _route_osrm(origin, dest)


def _route_osrm(origin: str, dest: str):
    og, dg = geocode(origin), geocode(dest)
    if not og:
        return None, f"I couldn't find '{origin}'."
    if not dg:
        return None, f"I couldn't find '{dest}'."
    olat, olon, _ = og
    dlat, dlon, dlabel = dg
    try:
        data = requests.get(f"{_OSRM}/{olon},{olat};{dlon},{dlat}",
                            params={"overview": "false"}, timeout=12).json()
    except Exception as e:
        return None, f"Routing error: {type(e).__name__}: {e}"
    routes = data.get("routes") or []
    if not routes:
        return None, f"I couldn't find a driving route to {dlabel}."
    r = routes[0]
    return {"duration_sec": r["duration"], "distance_m": r["distance"],
            "traffic": False, "mode": "driving", "dest_label": dlabel}, None


def _route_google(origin: str, dest: str, mode: str, key: str):
    params = {"origin": origin, "destination": dest, "mode": mode, "key": key}
    if mode == "driving":
        params["departure_time"] = "now"  # unlocks duration_in_traffic
    try:
        data = requests.get(_GOOGLE, params=params, timeout=12).json()
    except Exception as e:
        return None, f"Routing error: {type(e).__name__}: {e}"
    if data.get("status") != "OK" or not data.get("routes"):
        return None, f"Maps couldn't route that ({data.get('status', 'no route')})."
    leg = data["routes"][0]["legs"][0]
    dur = leg.get("duration_in_traffic") or leg["duration"]
    return {"duration_sec": dur["value"], "distance_m": leg["distance"]["value"],
            "traffic": "duration_in_traffic" in leg, "mode": mode,
            "dest_label": leg.get("end_address", dest)}, None


def _say(res: dict) -> str:
    mins = max(1, round(res["duration_sec"] / 60))
    km = res["distance_m"] / 1000
    traffic = " in current traffic" if res["traffic"] else ""
    return f"About {mins} min ({km:.0f} km) {res['mode']} to {res['dest_label']}{traffic}."


def _parse_time(s: str):
    """'HH:MM' (next occurrence) or an ISO datetime → datetime, else None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    try:
        h, m = s.split(":")
        now = datetime.now()
        t = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        return t + timedelta(days=1) if t < now else t
    except Exception:
        return None


def get_commute(destination: str, origin: str = "", mode: str = "driving") -> str:
    """Travel time and distance to a destination. origin defaults to home
    (JADE_HOME_LOCATION). mode is driving (default), transit, or walking
    (transit/walking need JADE_MAPS_API_KEY)."""
    o, d = _place(origin or "home"), _place(destination)
    if not d:
        return "Where to? I didn't catch a destination."
    if not o:
        return ("I don't know where you're starting from — tell me an origin, or set "
                "JADE_HOME_LOCATION in .env.")
    res, err = _route(o, d, mode)
    return err or _say(res)


def leave_by(destination: str, arrive_time: str, origin: str = "", mode: str = "driving") -> str:
    """When to leave to arrive by a given time. arrive_time is 'HH:MM' or ISO."""
    o, d = _place(origin or "home"), _place(destination)
    if not d:
        return "Where to? I didn't catch a destination."
    if not o:
        return ("I don't know where you're starting from — tell me an origin, or set "
                "JADE_HOME_LOCATION in .env.")
    arr = _parse_time(arrive_time)
    if arr is None:
        return "When do you need to arrive? Give me a time like 9:00."
    res, err = _route(o, d, mode)
    if err:
        return err
    leave = arr - timedelta(seconds=res["duration_sec"])
    mins = max(1, round(res["duration_sec"] / 60))
    return (f"Leave by {leave.strftime('%H:%M')} to reach {res['dest_label']} by "
            f"{arr.strftime('%H:%M')} — it's about {mins} min {res['mode']}.")
