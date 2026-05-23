"""Cross-platform OS integration.

One place for the handful of things Jade does that differ per operating system:
opening URLs/apps, desktop notifications, screenshots, and battery status.

Every helper dispatches on the running platform and **degrades to a clear
string** instead of raising — a missing tool on one OS should never crash the
voice loop. Public names mirror the old Linux-only modules so tools/registry.py
and the tool wrappers keep working unchanged.

  Linux   — the existing CLI tools (xdg-open, notify-send, grim/scrot, ...)
  macOS   — built-ins: open, osascript, screencapture
  Windows — os.startfile, a .NET balloon toast, media-key scancodes, ImageGrab
"""
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")


def platform_name() -> str:
    if IS_MAC:
        return "macos"
    if IS_WINDOWS:
        return "windows"
    if IS_LINUX:
        return "linux"
    return sys.platform


def _run(cmd, timeout: int = 10, **kw) -> tuple[bool, str]:
    """Run a command, capture output. Returns (ok, stderr-or-error)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return r.returncode == 0, (r.stderr or "").strip()
    except FileNotFoundError:
        return False, f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:  # noqa: BLE001 — never propagate to the voice loop
        return False, str(e)


def _spawn(cmd) -> tuple[bool, str]:
    """Fire-and-forget launch, output discarded. Returns (ok, error)."""
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, ""
    except FileNotFoundError:
        return False, f"{cmd[0]} not found"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# --------------------------------------------------------------------------- #
# Open URL / app
# --------------------------------------------------------------------------- #
def open_url(url: str) -> str:
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url

    if IS_WINDOWS:
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return f"Opened {url} in default browser"
        except Exception as e:  # noqa: BLE001
            return f"Failed to open URL: {e}"

    if IS_MAC:
        ok, err = _run(["open", url], timeout=8)
        return f"Opened {url} in default browser" if ok else f"Failed to open URL: {err}"

    # Linux
    if not shutil.which("xdg-open"):
        return "xdg-open not installed (install your distro's xdg-utils package)."
    ok, err = _spawn(["xdg-open", url])
    return f"Opened {url} in default browser" if ok else f"Failed to open URL: {err}"


def open_app(app: str) -> str:
    """Open an application by name."""
    if IS_WINDOWS:
        # `start` is a cmd builtin; the empty "" is the window-title arg.
        ok, err = _spawn(["cmd", "/c", "start", "", app])
        return f"Launched {app}" if ok else f"Failed to start {app}: {err}"

    if IS_MAC:
        ok, err = _run(["open", "-a", app], timeout=8)
        if ok:
            return f"Launched {app}"
        if shutil.which(app):
            ok2, err2 = _spawn([app])
            return f"Launched {app}" if ok2 else f"Failed to start {app}: {err2}"
        return f"Couldn't launch {app}: {err}"

    # Linux: .desktop launchers first, then raw binary.
    if shutil.which("gtk-launch"):
        ok, _ = _spawn(["gtk-launch", app])
        if ok:
            return f"Launched {app}"
    if shutil.which("kioclient5"):
        ok, _ = _spawn(["kioclient5", "exec", app])
        if ok:
            return f"Launched {app} (kioclient)"
    if shutil.which(app):
        ok, err = _spawn([app])
        return f"Launched {app}" if ok else f"Failed to start {app}: {err}"
    return f"Couldn't find {app}. Is it installed?"


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
def notify(title: str, body: str = "") -> str:
    if IS_MAC:
        t = title.replace('"', '\\"')
        b = body.replace('"', '\\"')
        ok, err = _run(["osascript", "-e", f'display notification "{b}" with title "{t}"'], timeout=6)
        return f"Notification sent: {title}" if ok else f"Notification failed: {err}"

    if IS_WINDOWS:
        return _notify_windows(title, body)

    # Linux
    if not shutil.which("notify-send"):
        return "notify-send not installed (install your distro's libnotify package)."
    ok, err = _run(["notify-send", title, body], timeout=5)
    return f"Notification sent: {title}" if ok else f"Notification failed: {err}"


def _notify_windows(title: str, body: str) -> str:
    """Balloon toast via .NET NotifyIcon — present on any Windows with .NET,
    so no extra pip dependency. Best-effort."""
    t = title.replace("'", "''")
    b = body.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$n=New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon=[System.Drawing.SystemIcons]::Information;"
        f"$n.BalloonTipTitle='{t}';$n.BalloonTipText='{b}';"
        "$n.Visible=$true;$n.ShowBalloonTip(5000);Start-Sleep -Milliseconds 6000;$n.Dispose()"
    )
    ok, err = _run(["powershell", "-NoProfile", "-Command", ps], timeout=10)
    return f"Notification sent: {title}" if ok else f"Notification failed: {err}"


# --------------------------------------------------------------------------- #
# Screenshot
# --------------------------------------------------------------------------- #
def screenshot(path: str = "") -> str:
    """Fullscreen screenshot to `path`, or ~/Pictures/Screenshots/ if unset."""
    if not path:
        out_dir = Path.home() / "Pictures" / "Screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = str(out_dir / f"shot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png")
    else:
        path = os.path.expanduser(path)

    if IS_MAC:
        ok, _ = _run(["screencapture", "-x", path], timeout=10)
        if ok and os.path.exists(path):
            return f"Screenshot saved to {path}"

    if IS_LINUX:
        for cmd in (["spectacle", "-b", "-f", "-o", path], ["grim", path], ["scrot", path]):
            if not shutil.which(cmd[0]):
                continue
            ok, _ = _run(cmd, timeout=10)
            if ok and os.path.exists(path):
                return f"Screenshot saved to {path}"

    # Windows, and fallback for the others (X11; Wayland usually blocks this).
    try:
        from PIL import ImageGrab
        ImageGrab.grab().save(path)
        return f"Screenshot saved to {path}"
    except Exception as e:  # noqa: BLE001
        return f"No working screenshot method on {platform_name()} ({e})."


# --------------------------------------------------------------------------- #
# Battery
# --------------------------------------------------------------------------- #
def battery_status() -> str:
    try:
        import psutil
        batt = psutil.sensors_battery()
        if batt is None:
            return "No battery info available"
        state = "charging" if batt.power_plugged else "on battery"
        return f"Battery: {int(batt.percent)}% ({state})"
    except ImportError:
        return _battery_sysfs()
    except Exception as e:  # noqa: BLE001
        return f"Battery info unavailable ({e})"


def _battery_sysfs() -> str:
    """Linux fallback when psutil isn't installed."""
    bat = Path("/sys/class/power_supply")
    if not bat.exists():
        return "No battery info available"
    for d in bat.iterdir():
        if d.name.startswith("BAT"):
            try:
                cap = (d / "capacity").read_text().strip()
                status = (d / "status").read_text().strip()
                return f"Battery: {cap}% ({status})"
            except Exception:  # noqa: BLE001
                continue
    return "No battery found"
