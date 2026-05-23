"""Media control via playerctl. Talks to any MPRIS player (Spotify, mpv, VLC,
Firefox playing audio, etc.)."""
import shutil
import subprocess


def _playerctl(*args) -> str:
    if not shutil.which("playerctl"):
        return "playerctl not installed. Try: sudo pacman -S playerctl"
    try:
        r = subprocess.run(["playerctl", *args],
                           capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return "playerctl timed out"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if r.returncode != 0 and err:
        return f"playerctl error: {err}"
    return out or "ok"


def media_play_pause() -> str:
    return _playerctl("play-pause")


def media_play() -> str:
    return _playerctl("play")


def media_pause() -> str:
    return _playerctl("pause")


def media_next() -> str:
    return _playerctl("next")


def media_prev() -> str:
    return _playerctl("previous")


def media_status() -> str:
    """Return current play status + title."""
    status = _playerctl("status")
    title = _playerctl("metadata", "--format", "{{artist}} — {{title}}")
    if "error" in status.lower() or "No players" in status:
        return status
    return f"{status}: {title}"


def media_set_volume(percent: int) -> str:
    """Set player volume 0..100."""
    try:
        percent = int(percent)
    except (TypeError, ValueError):
        return "Volume must be an integer 0..100"
    percent = max(0, min(100, percent))
    return _playerctl("volume", str(percent / 100.0))
