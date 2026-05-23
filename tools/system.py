"""System info + notifications + screenshots."""
import datetime
import os
import shutil
import subprocess
from pathlib import Path


def current_time() -> str:
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d %Y, %H:%M:%S")


def notify(title: str, body: str = "") -> str:
    if not shutil.which("notify-send"):
        return "notify-send not installed. Try: sudo pacman -S libnotify"
    try:
        subprocess.run(["notify-send", title, body], timeout=5)
        return f"Notification sent: {title}"
    except Exception as e:
        return f"Notification failed: {e}"


def screenshot(path: str = "") -> str:
    """Take a fullscreen screenshot. Saves to path or to ~/Pictures/Screenshots/."""
    if not path:
        out_dir = Path.home() / "Pictures" / "Screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = str(out_dir / f"shot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png")
    else:
        path = os.path.expanduser(path)

    # Try spectacle (KDE), then grim (wlroots), then scrot (X11).
    for cmd in (
        ["spectacle", "-b", "-f", "-o", path],
        ["grim", path],
        ["scrot", path],
    ):
        if not shutil.which(cmd[0]):
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and os.path.exists(path):
                return f"Screenshot saved to {path}"
        except Exception:
            continue
    return "No working screenshot tool found. Try: sudo pacman -S spectacle"


def battery_status() -> str:
    """Return battery level + charging state if a battery is present."""
    bat = Path("/sys/class/power_supply")
    if not bat.exists():
        return "No battery info available"
    for d in bat.iterdir():
        if d.name.startswith("BAT"):
            try:
                cap = (d / "capacity").read_text().strip()
                status = (d / "status").read_text().strip()
                return f"Battery: {cap}% ({status})"
            except Exception:
                continue
    return "No battery found"
