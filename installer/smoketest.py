#!/usr/bin/env python3
"""Post-install smoke test — run by the project venv's python so it exercises
the actually-installed environment. Verifies each core component really works.

Exit 0 if the two essentials (LLM + TTS) pass; non-zero otherwise.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_results = {}


def check(name, fn):
    try:
        msg = fn()
        _results[name] = True
        print(f"  PASS  {name}: {msg}", flush=True)
    except Exception as e:
        _results[name] = False
        print(f"  FAIL  {name}: {type(e).__name__}: {e}", flush=True)


def _llm():
    import llm
    out = llm.chat([{"role": "user", "content": "Reply with the single word: ok"}],
                   temperature=0)
    return f"model replied {out.strip()[:40]!r}"


def _tts():
    # _ensure_engine() loads Kokoro and runs the espeak phonemizer self-check.
    from voice.text_to_speech import _ensure_engine
    return f"engine={_ensure_engine()}"


def _asr():
    import faster_whisper  # noqa: F401
    return "faster-whisper importable"


def _audio():
    import sounddevice as sd
    return f"{len(sd.query_devices())} audio device(s)"


print("== Jade smoke test ==", flush=True)
check("LLM (Ollama)", _llm)
check("TTS (Kokoro/espeak)", _tts)
check("ASR (faster-whisper)", _asr)
check("Audio (PortAudio)", _audio)

core_ok = _results.get("LLM (Ollama)") and _results.get("TTS (Kokoro/espeak)")
print(f"\nRESULT: {'PASS' if core_ok else 'FAIL'}", flush=True)
sys.exit(0 if core_ok else 1)
