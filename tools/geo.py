"""Shared no-key geocoding via Open-Meteo's geocoding API.

Turns a place name (or a literal "lat,lon") into (lat, lon, label). Factored out
of tools/weather.py so the weather and commute tools share one implementation.
Returns None on anything unresolvable; never raises.
"""
import requests

_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"


def geocode(place: str):
    """Return (lat, lon, label) for a city/place name or 'lat,lon', else None."""
    place = (place or "").strip()
    if not place:
        return None
    if "," in place:  # literal "lat,lon"
        a, _, b = place.partition(",")
        try:
            return float(a), float(b), place
        except ValueError:
            pass
    try:
        r = requests.get(_GEOCODE, params={"name": place, "count": 1}, timeout=10)
        results = r.json().get("results") or []
        if not results:
            return None
        g = results[0]
        label = ", ".join(x for x in (g.get("name"), g.get("country_code")) if x)
        return g["latitude"], g["longitude"], label
    except Exception:
        return None
