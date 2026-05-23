"""Cross-platform media control.

  Linux   — playerctl (MPRIS): works with Spotify, mpv, VLC, browsers, ...
  macOS   — AppleScript to Spotify (preferred) or Apple Music
  Windows — global media-key scancodes via ctypes (drives whatever app has the
            session). Reading 'what's playing' and setting an exact volume
            aren't available through media keys, so those degrade to a message.
"""
import shutil
import subprocess
import sys

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")


# --------------------------------------------------------------------------- #
# Linux — playerctl
# --------------------------------------------------------------------------- #
def _playerctl(*args) -> str:
    if not shutil.which("playerctl"):
        return "playerctl not installed (install it via your distro's package manager)."
    try:
        r = subprocess.run(["playerctl", *args], capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return "playerctl timed out"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if r.returncode != 0 and err:
        return f"playerctl error: {err}"
    return out or "ok"


# --------------------------------------------------------------------------- #
# macOS — AppleScript to Spotify / Music
# --------------------------------------------------------------------------- #
def _osa(script: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=6)
        return r.returncode == 0, (r.stdout or r.stderr or "").strip()
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def _mac_app() -> str | None:
    """Whichever supported player is currently running (Spotify wins)."""
    for app in ("Spotify", "Music"):
        ok, out = _osa(f'tell application "System Events" to (name of processes) contains "{app}"')
        if ok and out.lower() == "true":
            return app
    return None


def _mac_control(command: str) -> str:
    app = _mac_app()
    if not app:
        return "No media player running (open Spotify or Music)."
    ok, out = _osa(f'tell application "{app}" to {command}')
    return out or ("ok" if ok else f"control failed: {out}")


# --------------------------------------------------------------------------- #
# Windows — media-key scancodes
# --------------------------------------------------------------------------- #
_VK = {
    "play_pause": 0xB3, "next": 0xB0, "prev": 0xB1,
    "vol_up": 0xAF, "vol_down": 0xAE, "mute": 0xAD,
}


def _win_key(name: str) -> str:
    try:
        import ctypes
        vk = _VK[name]
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"media key failed: {e}"


# --------------------------------------------------------------------------- #
# Public API (names imported by tools/registry.py)
# --------------------------------------------------------------------------- #
def media_play_pause() -> str:
    if IS_WINDOWS:
        return _win_key("play_pause")
    if IS_MAC:
        return _mac_control("playpause")
    return _playerctl("play-pause")


def media_play() -> str:
    if IS_WINDOWS:
        return _win_key("play_pause")
    if IS_MAC:
        return _mac_control("play")
    return _playerctl("play")


def media_pause() -> str:
    if IS_WINDOWS:
        return _win_key("play_pause")
    if IS_MAC:
        return _mac_control("pause")
    return _playerctl("pause")


def media_next() -> str:
    if IS_WINDOWS:
        return _win_key("next")
    if IS_MAC:
        return _mac_control("next track")
    return _playerctl("next")


def media_prev() -> str:
    if IS_WINDOWS:
        return _win_key("prev")
    if IS_MAC:
        return _mac_control("previous track")
    return _playerctl("previous")


def media_status() -> str:
    """Current play state + title, where the platform can report it."""
    if IS_WINDOWS:
        return "Can't read what's playing on Windows (media keys are write-only)."
    if IS_MAC:
        app = _mac_app()
        if not app:
            return "No media player running."
        ok, state = _osa(f'tell application "{app}" to player state as string')
        _, artist = _osa(f'tell application "{app}" to artist of current track')
        _, title = _osa(f'tell application "{app}" to name of current track')
        meta = " — ".join(x for x in (artist, title) if x)
        return f"{state}: {meta}" if meta else state
    status = _playerctl("status")
    title = _playerctl("metadata", "--format", "{{artist}} — {{title}}")
    if "error" in status.lower() or "No players" in status:
        return status
    return f"{status}: {title}"


def media_set_volume(percent: int) -> str:
    """Set player volume 0..100 (where supported)."""
    try:
        percent = int(percent)
    except (TypeError, ValueError):
        return "Volume must be an integer 0..100"
    percent = max(0, min(100, percent))
    if IS_WINDOWS:
        return "Exact volume isn't settable on Windows here; use the volume keys."
    if IS_MAC:
        app = _mac_app()
        if not app:
            return "No media player running."
        ok, out = _osa(f'tell application "{app}" to set sound volume to {percent}')
        return f"Volume set to {percent}%" if ok else f"Volume failed: {out}"
    return _playerctl("volume", str(percent / 100.0))
