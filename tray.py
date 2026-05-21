import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import threading
import os


def create_icon():

    image = Image.new("RGB", (64, 64), (30, 30, 30))
    dc = ImageDraw.Draw(image)
    dc.rectangle([16, 16, 48, 48], fill=(0, 200, 255))

    return image


def on_exit(icon, item):
    icon.stop()
    os._exit(0)


def run_tray():

    icon = pystray.Icon(
        "AI Companion",
        create_icon(),
        menu=pystray.Menu(
            item("Exit", on_exit)
        )
    )

    icon.run()