"""System-tray icon. Pure cosmetic — Exit menu cleanly stops the whole app.

On Arch needs libayatana-appindicator + pystray; missing deps are handled by the launcher
which wraps run_tray() in try/except.
"""
import pystray
from PIL import Image, ImageDraw
from pystray import MenuItem as item

from shared_state import STOP_EVENT


def _create_icon():
    image = Image.new("RGB", (64, 64), (30, 30, 30))
    dc = ImageDraw.Draw(image)
    dc.rectangle([16, 16, 48, 48], fill=(0, 200, 255))
    return image


def _on_exit(icon, _item):
    # Signal the main (tk) thread to quit; it'll fall through launcher.py and
    # let atexit handlers (Chroma flush) run. Calling sys.exit() here would only
    # raise SystemExit in this daemon thread and leave the app running.
    STOP_EVENT.set()
    icon.stop()


def run_tray():
    icon = pystray.Icon(
        "Companion",
        _create_icon(),
        menu=pystray.Menu(item("Exit", _on_exit)),
    )
    icon.run()
