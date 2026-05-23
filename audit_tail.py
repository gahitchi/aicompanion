"""Pretty-tail the Companion's audit log.

Usage:
    python audit_tail.py             # show last 20 then follow
    python audit_tail.py -n 50       # show last 50 then follow
    python audit_tail.py --summary   # aggregate stats over last N entries
"""
import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

LOG = Path.home() / ".aicompanion" / "audit.log"


def _fmt(record: dict) -> str:
    t = record.get("t", "")
    tool = record.get("tool", "?")
    args = record.get("args", {})
    args_brief = ", ".join(f"{k}={v!r}"[:60] for k, v in (args or {}).items())
    ok = "✓" if record.get("ok") else "✗"
    conf = " (confirmed)" if record.get("confirmed") else ""
    if record.get("tier") == "confirm":
        suffix = "  ⟶  PENDING: " + record.get("description", "")
    else:
        result = str(record.get("result", ""))
        result = result[:120].replace("\n", "↵")
        suffix = f"  ⟶  {result}"
    return f"{t} {ok}{conf} {tool}({args_brief}){suffix}"


def _read_records(limit: int = None):
    if not LOG.exists():
        return []
    with open(LOG) as f:
        lines = f.readlines()
    if limit is not None:
        lines = lines[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def _print_summary(records: list) -> None:
    if not records:
        print("(no audit entries yet)")
        return
    counts = Counter(r.get("tool", "?") for r in records)
    ok_by_tool = defaultdict(lambda: [0, 0])  # [ok, total]
    confirmed = 0
    pending = 0
    denied = 0
    for r in records:
        tool = r.get("tool", "?")
        ok_by_tool[tool][1] += 1
        if r.get("ok"):
            ok_by_tool[tool][0] += 1
        if r.get("confirmed"):
            confirmed += 1
        if r.get("tier") == "confirm":
            pending += 1
        result = str(r.get("result", ""))
        if "Refused" in result or "denied" in result.lower():
            denied += 1

    first = records[0].get("t", "?")
    last = records[-1].get("t", "?")
    print(f"--- audit summary ({len(records)} entries from {first} → {last}) ---")
    print()
    print(f"{'tool':<22} {'calls':>6} {'ok%':>6}")
    print("-" * 38)
    for tool, n in counts.most_common():
        ok, total = ok_by_tool[tool]
        pct = (100.0 * ok / total) if total else 0
        print(f"{tool:<22} {n:>6} {pct:>5.0f}%")
    print()
    print(f"  CONFIRM-pending: {pending}    confirmed-then-ran: {confirmed}    DENY/refused: {denied}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-n", type=int, default=20, help="lines of history to show / summarize")
    p.add_argument("-f", "--follow", action="store_true", default=True)
    p.add_argument("--summary", action="store_true", help="aggregate stats and exit")
    args = p.parse_args()

    if not LOG.exists():
        print(f"No audit log at {LOG} yet. Jade will create one once she runs a tool.")
        return

    if args.summary:
        _print_summary(_read_records(limit=args.n if args.n != 20 else None))
        return

    records = _read_records(limit=args.n)
    for r in records:
        print(_fmt(r))

    if not args.follow:
        return

    print("\n--- following new entries (Ctrl+C to quit) ---")
    pos = LOG.stat().st_size
    try:
        while True:
            cur = LOG.stat().st_size
            if cur > pos:
                with open(LOG) as f:
                    f.seek(pos)
                    for line in f:
                        try:
                            print(_fmt(json.loads(line)))
                        except json.JSONDecodeError:
                            print(line.rstrip())
                pos = cur
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    sys.exit(main() or 0)
