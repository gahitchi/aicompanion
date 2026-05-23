"""System info + notifications + screenshots.

`current_time` is pure Python; the OS-specific bits (notify / screenshot /
battery) are delegated to the cross-platform `platform_io` adapter and
re-exported here so the registry keeps importing them from tools.system.
"""
import datetime

from platform_io import battery_status, notify, screenshot  # noqa: F401  (re-export)


def current_time() -> str:
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d %Y, %H:%M:%S")
