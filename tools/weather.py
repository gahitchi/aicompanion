"""Weather tool — current conditions + short forecast via Open-Meteo (free, no key).

Location comes from the `location` arg, else JADE_WEATHER_LOCATION (a city name
or 'lat,lon'). Units follow JADE_WEATHER_UNITS (metric|imperial). SAFE — read only.
Fails open with a hint when no location is resolvable.
"""
import os

import requests

_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> short description.
_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


def _units() -> dict:
    if os.environ.get("JADE_WEATHER_UNITS", "metric").lower().startswith("imp"):
        return {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "tsym": "F", "wsym": "mph"}
    return {"temperature_unit": "celsius", "wind_speed_unit": "kmh", "tsym": "C", "wsym": "km/h"}


def _resolve_location(location: str):
    """Return (lat, lon, label) or None."""
    location = (location or os.environ.get("JADE_WEATHER_LOCATION") or "").strip()
    if not location:
        return None
    if "," in location:  # literal "lat,lon"
        a, _, b = location.partition(",")
        try:
            return float(a), float(b), location
        except ValueError:
            pass
    try:
        r = requests.get(_GEOCODE, params={"name": location, "count": 1}, timeout=10)
        results = r.json().get("results") or []
        if not results:
            return None
        g = results[0]
        label = ", ".join(x for x in (g.get("name"), g.get("country_code")) if x)
        return g["latitude"], g["longitude"], label
    except Exception:
        return None


def get_weather(location: str = None, when: str = "now") -> str:
    """Current weather (when='now') or a short daily forecast
    (when='today'/'tomorrow'/'week'). SAFE."""
    loc = _resolve_location(location)
    if loc is None:
        return ("I don't have a location for weather. Tell me a city, or set "
                "JADE_WEATHER_LOCATION in .env (a city name or 'lat,lon').")
    lat, lon, label = loc
    u = _units()
    try:
        params = {
            "latitude": lat, "longitude": lon,
            "temperature_unit": u["temperature_unit"],
            "wind_speed_unit": u["wind_speed_unit"],
            "timezone": "auto",
        }
        if when in ("week", "today", "tomorrow"):
            params["daily"] = ("weather_code,temperature_2m_max,temperature_2m_min,"
                               "precipitation_probability_max")
        else:
            params["current"] = "temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
        data = requests.get(_FORECAST, params=params, timeout=10).json()
    except Exception as e:
        return f"Weather error: {type(e).__name__}: {e}"

    if when in ("week", "today", "tomorrow"):
        d = data.get("daily", {})
        days = d.get("time", [])
        if not days:
            return f"No forecast available for {label}."
        if when == "today":
            idxs = range(0, 1)
        elif when == "tomorrow":
            idxs = range(1, min(2, len(days)))
        else:
            idxs = range(0, min(7, len(days)))
        pops = d.get("precipitation_probability_max", [None] * len(days))
        lines = []
        for i in idxs:
            code = _WMO.get(d["weather_code"][i], "mixed")
            hi, lo = d["temperature_2m_max"][i], d["temperature_2m_min"][i]
            pop = pops[i]
            rain = f", {pop}% rain" if pop is not None else ""
            lines.append(f"{days[i]}: {code}, {lo:.0f}-{hi:.0f}{u['tsym']}{rain}")
        return f"Forecast for {label}:\n" + "\n".join(lines)

    c = data.get("current", {})
    if not c:
        return f"No current weather for {label}."
    code = _WMO.get(c.get("weather_code"), "mixed")
    return (f"{label}: {code}, {c.get('temperature_2m')}{u['tsym']} "
            f"(feels like {c.get('apparent_temperature')}{u['tsym']}), "
            f"wind {c.get('wind_speed_10m')} {u['wsym']}.")
