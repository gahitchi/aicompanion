"""App and URL launchers via xdg-open."""
import shutil
import subprocess


def open_url(url: str) -> str:
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    if not shutil.which("xdg-open"):
        return "xdg-open not installed. Try: sudo pacman -S xdg-utils"
    try:
        subprocess.Popen(["xdg-open", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return f"Failed to open URL: {e}"
    return f"Opened {url} in default browser"


def open_app(app: str) -> str:
    """Open an application. Tries `gtk-launch` for .desktop entries, then
    `xdg-open` as fallback, then runs the binary directly if present in PATH."""
    # 1. Try gtk-launch with .desktop name (works for most installed apps)
    if shutil.which("gtk-launch"):
        try:
            subprocess.Popen(["gtk-launch", app],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Launched {app}"
        except Exception:
            pass
    # 2. Try kioclient5 for KDE
    if shutil.which("kioclient5"):
        try:
            subprocess.Popen(["kioclient5", "exec", app],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Launched {app} (kioclient)"
        except Exception:
            pass
    # 3. Direct binary
    if shutil.which(app):
        try:
            subprocess.Popen([app],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Launched {app}"
        except Exception as e:
            return f"Failed to start {app}: {e}"
    return f"Couldn't find {app}. Is it installed?"
