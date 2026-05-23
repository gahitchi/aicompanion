"""Tone classifier calibration: live mic → features → per-tone scores.

Run with:
    python tone_demo.py

Speak a few utterances in different registers (whisper, normal, loud, joking,
angry, tired, etc.). For each segment, prints:
  - the raw acoustic + lexical features
  - the per-tone scores
  - the classified tone

Use this to dial in voice/tone.py:
  - the ramp thresholds (TONE_RMS_LOW, TONE_PITCH_LOW, etc. via env vars)
  - the per-feature weights inside the _score_* functions

Quits on Ctrl+C or when you say 'goodbye companion'.

This script does NOT call the LLM or play anything — it's mic-in, text-out.
"""
import os
import sys

# Force the tone module's debug logger so every classification prints.
os.environ.setdefault("ASR_TONE_LOG", "1")

# Avoid the model preload overhead in streaming_asr — we still need Whisper
# (the script transcribes), but flag any failures clearly.
from voice.streaming_asr import stream_recognition  # noqa: E402
from voice.tone import classify  # noqa: E402


def main():
    print("tone_demo — speak into the mic in different registers. Ctrl+C to quit.")
    print(f"Active thresholds: RMS [{os.environ.get('TONE_RMS_LOW', '350')},"
          f" {os.environ.get('TONE_RMS_HIGH', '2200')}]"
          f" Pitch [{os.environ.get('TONE_PITCH_LOW', '130')},"
          f" {os.environ.get('TONE_PITCH_HIGH', '260')}] Hz")
    print()
    try:
        for text, features in stream_recognition():
            text = text.strip()
            if not text:
                continue
            tone = classify(text, features)
            # the tone module already prints the dbg line (ASR_TONE_LOG=1) —
            # all we add here is the transcription so you know what segment
            # produced which scores.
            print(f"  └─ heard: {text!r}\n")
            if "goodbye companion" in text:
                print("Bye.")
                return
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    sys.exit(main() or 0)
