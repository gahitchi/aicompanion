"""Unit and currency conversion.

Units convert locally — no network, no extra dependency: a factor table per
dimension (everything normalized to a base unit) plus a special case for
temperature. Currency uses frankfurter.app (European Central Bank rates, free,
no key) when both sides are 3-letter ISO codes. SAFE; fails open with a clear
message. Generous aliases so spoken words ("cups", "pounds", "miles") resolve.
"""
import time

import requests

# canonical unit -> factor to that dimension's base unit
_LENGTH = {"m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001, "mi": 1609.344,
           "yd": 0.9144, "ft": 0.3048, "in": 0.0254, "nmi": 1852.0}
_MASS = {"kg": 1.0, "g": 0.001, "mg": 1e-6, "lb": 0.45359237,
         "oz": 0.028349523125, "st": 6.35029318, "t": 1000.0}
_VOLUME = {"l": 1.0, "ml": 0.001, "cl": 0.01, "m3": 1000.0, "gal": 3.785411784,
           "qt": 0.946352946, "pt": 0.473176473, "cup": 0.2365882365,
           "floz": 0.0295735296, "tbsp": 0.0147867648, "tsp": 0.00492892159}
_TIME = {"s": 1.0, "min": 60.0, "h": 3600.0, "day": 86400.0, "week": 604800.0}
_DATA = {"b": 1.0, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12,
         "kib": 1024.0, "mib": 1024.0 ** 2, "gib": 1024.0 ** 3, "tib": 1024.0 ** 4}
_SPEED = {"mps": 1.0, "kmh": 1 / 3.6, "mph": 0.44704, "kn": 0.514444}

_DIMS = {"length": _LENGTH, "mass": _MASS, "volume": _VOLUME,
         "time": _TIME, "data": _DATA, "speed": _SPEED}
_TEMP = {"c", "f", "k"}
_ALL_UNITS = set().union(*(d.keys() for d in _DIMS.values())) | _TEMP

_ALIASES = {
    # length
    "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "kilometer": "km", "kilometers": "km", "kilometre": "km", "kilometres": "km",
    "centimeter": "cm", "centimeters": "cm", "millimeter": "mm", "millimeters": "mm",
    "mile": "mi", "miles": "mi", "yard": "yd", "yards": "yd",
    "foot": "ft", "feet": "ft", "inch": "in", "inches": "in", "nauticalmile": "nmi",
    # mass
    "kilogram": "kg", "kilograms": "kg", "kilo": "kg", "kilos": "kg",
    "gram": "g", "grams": "g", "milligram": "mg", "milligrams": "mg",
    "pound": "lb", "pounds": "lb", "lbs": "lb", "ounce": "oz", "ounces": "oz",
    "stone": "st", "tonne": "t", "tonnes": "t", "ton": "t",
    # volume
    "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml",
    "centiliter": "cl", "gallon": "gal", "gallons": "gal", "quart": "qt", "quarts": "qt",
    "pint": "pt", "pints": "pt", "cups": "cup", "fluidounce": "floz", "fluidounces": "floz",
    "tablespoon": "tbsp", "tablespoons": "tbsp", "teaspoon": "tsp", "teaspoons": "tsp",
    # time
    "second": "s", "seconds": "s", "sec": "s", "secs": "s",
    "minute": "min", "minutes": "min", "mins": "min",
    "hour": "h", "hours": "h", "hr": "h", "hrs": "h", "days": "day", "weeks": "week",
    # data
    "byte": "b", "bytes": "b", "kilobyte": "kb", "kilobytes": "kb",
    "megabyte": "mb", "megabytes": "mb", "gigabyte": "gb", "gigabytes": "gb",
    "terabyte": "tb", "terabytes": "tb",
    # speed
    "kph": "kmh", "kmph": "kmh", "kilometersperhour": "kmh",
    "milesperhour": "mph", "meterspersecond": "mps", "knot": "kn", "knots": "kn",
    # temperature
    "celsius": "c", "centigrade": "c", "fahrenheit": "f", "kelvin": "k",
    "°c": "c", "°f": "f", "degc": "c", "degf": "f",
}

_FX = "https://api.frankfurter.app/latest"
_fx_cache: dict = {}  # (from, to) -> (rate, timestamp)


def _canon(u: str) -> str:
    u = (u or "").strip().lower().replace(" ", "").rstrip(".")
    return _ALIASES.get(u, u)


def _num(x: float) -> str:
    """Trim a float to a spoken-friendly form (no trailing zeros)."""
    return f"{x:.4g}" if abs(x) < 1 else f"{round(x, 2):g}"


def _to_celsius(v: float, u: str) -> float:
    return v if u == "c" else (v - 32) * 5 / 9 if u == "f" else v - 273.15


def _from_celsius(c: float, u: str) -> float:
    return c if u == "c" else c * 9 / 5 + 32 if u == "f" else c + 273.15


def _temp_label(u: str) -> str:
    return "K" if u == "k" else "°" + u.upper()


def _currency(value: float, frm: str, to: str) -> str:
    frm, to = frm.upper(), to.upper()
    if frm == to:
        return f"{_num(value)} {frm} is {_num(value)} {to}."
    now = time.time()
    cached = _fx_cache.get((frm, to))
    if cached and now - cached[1] < 3600:
        rate = cached[0]
    else:
        try:
            data = requests.get(_FX, params={"from": frm, "to": to}, timeout=10).json()
            rate = data["rates"][to]
            _fx_cache[(frm, to)] = (rate, now)
        except Exception:
            return ("I couldn't fetch exchange rates just now — check the currency "
                    "codes or try again in a moment.")
    return f"{_num(value)} {frm} is about {value * rate:.2f} {to} (ECB rate)."


def convert(value: float, from_unit: str, to_unit: str) -> str:
    """Convert a value between units (length, mass, volume, time, data, speed,
    temperature) or between two currencies (3-letter codes, e.g. EUR to USD)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "Give me a number to convert."
    f, t = _canon(from_unit), _canon(to_unit)
    if not f or not t:
        return "Tell me what to convert from and to."

    if f in _TEMP or t in _TEMP:
        if f in _TEMP and t in _TEMP:
            out = _from_celsius(_to_celsius(value, f), t)
            return f"{_num(value)}{_temp_label(f)} is {out:.1f}{_temp_label(t)}."
        return "Temperatures only convert to temperatures (C, F, or K)."

    for table in _DIMS.values():
        if f in table and t in table:
            out = value * table[f] / table[t]
            return f"{_num(value)} {from_unit.strip()} is about {_num(out)} {to_unit.strip()}."

    # Currency only when neither side is a known unit (avoids 'gal'→'USD' nonsense).
    if (f not in _ALL_UNITS and t not in _ALL_UNITS
            and f.isalpha() and len(f) == 3 and t.isalpha() and len(t) == 3):
        return _currency(value, f, t)

    return f"I can't convert {from_unit} to {to_unit} — those aren't the same kind of unit."
