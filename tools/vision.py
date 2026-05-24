"""Vision tools — let Jade actually see the screen or an image file.

`see_screen` captures the display (reusing platform_io.screenshot) and
`look_at_image` reads a file; both hand the image to a local multimodal model
via llm.chat_vision. If the vision model isn't installed, return a friendly hint
rather than a raw error.
"""
import os
import tempfile
from pathlib import Path

import llm
import platform_io


def _describe(image_bytes: bytes, question: str) -> str:
    try:
        return llm.chat_vision(question, [image_bytes])
    except Exception as e:  # noqa: BLE001 — most likely the model isn't pulled
        return (f"I couldn't look at that ({type(e).__name__}). If the vision "
                f"model isn't installed yet, run: ollama pull {llm.VISION_MODEL}")


def see_screen(question: str = "") -> str:
    """Capture the current screen and describe it / answer a question about it."""
    tmp = str(Path(tempfile.gettempdir()) / "jade_screen.png")
    status = platform_io.screenshot(tmp)
    if not os.path.exists(tmp):
        return f"Couldn't capture the screen: {status}"
    try:
        with open(tmp, "rb") as f:
            data = f.read()
        return _describe(data, question or "Briefly describe what's on the screen.")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def look_at_image(path: str, question: str = "") -> str:
    """Describe / answer a question about an image file on disk."""
    p = os.path.expanduser(path)
    if not os.path.isfile(p):
        return f"No image file at {p}."
    with open(p, "rb") as f:
        data = f.read()
    return _describe(data, question or "Describe this image.")
