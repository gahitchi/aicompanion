"""Expense + budget tracking by voice.

"Spent 12 euros on lunch" → log_expense; "how much did I spend this week" →
expense_summary; "budget 200 a month for groceries" → set_budget. Everything
lives in a gitignored expenses.json beside the app (the lists.py load/save/lock
pattern). Owner-only — it's the owner's finances.

Amounts are stored with a currency (JADE_CURRENCY, default EUR); summaries report
totals and flag any category over its budget for the period.
"""
import json
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "expenses.json"
_LOCK = threading.Lock()


def _currency() -> str:
    return os.environ.get("JADE_CURRENCY", "EUR").strip().upper() or "EUR"


def _load() -> dict:
    try:
        data = json.loads(_PATH.read_text())
    except Exception:
        data = {}
    data.setdefault("log", [])
    data.setdefault("budgets", {})
    return data


def _save(data: dict) -> None:
    try:
        _PATH.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _period_start(period: str) -> date:
    today = date.today()
    p = (period or "week").strip().lower()
    if p == "month":
        return today.replace(day=1)
    if p in ("all", "ever", "total"):
        return date.min
    return today - timedelta(days=today.weekday())  # this week (Mon)


def _in_period(iso_date: str, start: date) -> bool:
    try:
        return datetime.fromisoformat(iso_date).date() >= start
    except Exception:
        return False


def log_expense(amount: float, category: str = "", note: str = "") -> str:
    """Record a spend. amount is a number; category like 'lunch'/'groceries'."""
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        return "How much was it? I need a number."
    cat = (category or "uncategorized").strip().lower()
    cur = _currency()
    with _LOCK:
        data = _load()
        data["log"].append({"date": datetime.now().isoformat(timespec="seconds"),
                            "amount": amount, "currency": cur,
                            "category": cat, "note": note.strip()})
        # month-to-date total for this category, for a useful confirmation
        start = _period_start("month")
        mtd = sum(e["amount"] for e in data["log"]
                  if e["category"] == cat and _in_period(e["date"], start))
        budget = data["budgets"].get(cat)
        _save(data)
    line = f"Logged {amount:.2f} {cur} for {cat}. That's {mtd:.2f} {cur} on {cat} this month"
    if budget and budget.get("period", "month") == "month":
        line += f" of your {budget['amount']:.0f} {cur} budget"
        if mtd > budget["amount"]:
            line += " — over budget"
    return line + "."


def expense_summary(period: str = "week") -> str:
    """Summarize spending for 'week' (default), 'month', or 'all', by category."""
    start = _period_start(period)
    cur = _currency()
    with _LOCK:
        data = _load()
    rows = [e for e in data["log"] if _in_period(e["date"], start)]
    if not rows:
        return f"No expenses logged for the {period}."
    by_cat: dict = {}
    for e in rows:
        by_cat[e["category"]] = by_cat.get(e["category"], 0.0) + e["amount"]
    total = sum(by_cat.values())
    lines = [f"Total this {period}: {total:.2f} {cur}."]
    for cat, amt in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        line = f"  {cat}: {amt:.2f} {cur}"
        b = data["budgets"].get(cat)
        if b:
            line += f" (budget {b['amount']:.0f}{'' if b.get('period')=='month' else '/'+b.get('period','month')}"
            line += ", over" if amt > b["amount"] else ", ok"
            line += ")"
        lines.append(line)
    return "\n".join(lines)


def set_budget(category: str, amount: float, period: str = "month") -> str:
    """Set a spending budget for a category (per 'month' by default, or 'week')."""
    cat = (category or "").strip().lower()
    if not cat:
        return "Which category is the budget for?"
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        return "What's the budget amount? I need a number."
    per = "week" if (period or "month").strip().lower().startswith("w") else "month"
    with _LOCK:
        data = _load()
        data["budgets"][cat] = {"amount": amount, "period": per}
        _save(data)
    return f"Set a {amount:.0f} {_currency()} per-{per} budget for {cat}."
