"""Voice memos and meeting notes.

add_memo files a quick spoken note — the live ASR already transcribed what the
user said, so this just stores it (kind="memo", recalled via recall_notes).
transcribe_file runs the Whisper model the service already keeps loaded over an
audio file (a recorded meeting, a voice note) and summarizes it to key points +
action items. We deliberately don't open a second mic stream — the running voice
loop owns the mic — so longer captures come in as files.

Owner-only (memos are the owner's private record). Fails open on a bad path / a
download or model hiccup. Long CPU transcription can take a little while.
"""
import os
from datetime import datetime
from pathlib import Path

from tools.safety import classify_path, SAFE

# Common audio containers Whisper (via ffmpeg) reads.
_AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".mp4"}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def add_memo(text: str) -> str:
    """Save a quick voice memo (the user dictated it; the live ASR transcribed it)."""
    text = (text or "").strip()
    if not text:
        return "What should the memo say?"
    import memory
    memory.save_memory(f"[memo {_today()}] {text}", kind="memo")
    return "Got it — saved that memo."


def transcribe_file(path: str) -> str:
    """Transcribe an audio recording and summarize it to key points + action
    items, saving the result as a memo. `path` is a local audio file in your
    home or /tmp."""
    p = Path(os.path.expanduser((path or "").strip()))
    if classify_path(str(p), "read") != SAFE:
        return f"I can only read files in your home or /tmp; {path} is outside that."
    if not p.exists():
        return f"I couldn't find a file at {p}."
    if p.suffix.lower() not in _AUDIO_EXT:
        return f"That doesn't look like an audio file ({p.suffix or 'no extension'})."
    try:
        from voice.streaming_asr import _ensure_model
        model = _ensure_model()
        segments, _info = model.transcribe(str(p), beam_size=1)
        transcript = " ".join(seg.text for seg in segments).strip()
    except Exception as e:
        return f"I couldn't transcribe that: {type(e).__name__}: {e}"
    if not transcript:
        return "I didn't catch any speech in that recording."

    import llm
    try:
        from persona import get_persona_prompt
        system = get_persona_prompt()
    except Exception:
        system = "You are a concise, warm assistant."
    capped = transcript[:12000]
    try:
        summary = llm.chat([
            {"role": "system", "content": system + "\n\nSummarize this transcript "
             "to be spoken aloud: a few key points and any clear action items or "
             "follow-ups. No markdown, no preamble."},
            {"role": "user", "content": capped},
        ], temperature=0.3).strip()
    except Exception:
        summary = transcript[:1500]  # model down → keep a raw excerpt

    import memory
    memory.save_memory(f"[memo {_today()} | from {p.name}] {summary}", kind="memo")
    return summary
