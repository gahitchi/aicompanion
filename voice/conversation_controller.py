"""Voice loop: stream mic → ASR → wake-word gate → LLM → TTS.

State machine:
  IDLE → on wake-word match, go ACTIVE. If the same utterance carried a real
         question after the wake word, run it now (single-breath flow).
  ACTIVE → every utterance is a turn with the Companion, until the user says
           "stop listening" / "goodbye companion".

Each transcription carries acoustic features (RMS, peak) from the speech
segment. We classify the tone (soft / neutral / intense) and pass it through
the LLM prompt + TTS speed/volume so the Companion's response matches.
"""
import os
import time

import events
import shared_state
from main import companion
from shared_state import SPEAKING, STOP_EVENT
from voice.streaming_asr import stream_recognition
from voice.text_to_speech import speak, speak_stream
from voice.tone import classify, update_tone_history, current_mode
from voice.wake_engine import detect_and_strip


SLEEP_PHRASES = {"stop listening", "goodbye companion", "go to sleep",
                 "goodbye jade", "stop listening jade"}

# Proactive speech gating.
_QUIET_START = int(os.environ.get("JADE_QUIET_START", "23"))
_QUIET_END = int(os.environ.get("JADE_QUIET_END", "8"))
_PROACTIVE_COOLDOWN = float(os.environ.get("JADE_PROACTIVE_COOLDOWN", "30"))


def _in_quiet_hours(now=None) -> bool:
    h = time.localtime(now).tm_hour
    if _QUIET_START == _QUIET_END:
        return False
    if _QUIET_START < _QUIET_END:
        return _QUIET_START <= h < _QUIET_END
    return h >= _QUIET_START or h < _QUIET_END  # wraps past midnight


def proactive_speaker(queue) -> None:
    """Drain the shared task_queue and voice events when it's a good moment.

    This is the consumer the autonomous loop + scheduler were missing — before,
    proactive messages and reminders were enqueued but never spoken. Reminders
    fire whenever she isn't already talking; proactive check-ins additionally
    respect quiet hours and don't interject right after the user spoke.
    """
    while not STOP_EVENT.is_set():
        time.sleep(1)
        if SPEAKING.is_set() or not queue:
            continue
        try:
            event = queue.pop(0)
        except IndexError:
            continue
        content = (event.get("content") or "").strip()
        if not content:
            continue
        etype = event.get("type")
        now = time.time()
        # Time-sensitive events fire whenever she isn't already talking; only
        # open-ended chatter (briefing / autonomous check-ins) respects quiet
        # hours + the post-user-speech cooldown.
        if etype not in ("reminder", "timer", "nudge"):
            if _in_quiet_hours(now):
                continue  # drop proactive chatter overnight
            if now - shared_state.LAST_USER_SPEECH < _PROACTIVE_COOLDOWN:
                continue  # mid-conversation — don't talk over the flow
        print(f"[proactive/{etype}] {content}")
        try:
            events.publish({"type": "said", "text": content,
                            "proactive": True, "kind": etype})
        except Exception:
            pass
        speak(content)


def _is_sleep(text: str) -> bool:
    lo = text.strip().lower().strip(".,!?;: ")
    return lo in SLEEP_PHRASES


def _handle_turn(text: str, tone: str = "neutral", lang: str = "en",
                 is_owner: bool = True, speaker: str = None) -> None:
    """Run one user turn through the LLM and speak the reply, matching tone.

    Streams tokens straight into TTS so the first sentence plays while the
    LLM is still generating the rest. `is_owner` gates personal memory: when
    the speaker isn't the enrolled owner, the agent runs without their private
    context. `speaker` is the recognized name (a known household member) or None.
    """
    events.publish({"type": "status", "state": "thinking"})
    try:
        token_stream = companion.chat_stream(text, tone=tone, lang=lang,
                                             is_owner=is_owner, speaker=speaker)
        events.publish({"type": "status", "state": "speaking"})
        response = speak_stream(token_stream, tone=tone, lang=lang)
    except Exception as e:
        print(f"[voice] chat error: {e}")
        events.publish({"type": "status", "state": "error", "error": str(e)})
        speak("Hm, something's off on my end. Try again?")
        return
    response = response.strip()
    print(f"[said]  ({tone}/{lang}) {response}")
    events.publish({
        "type": "said", "text": response, "tone": tone, "mode": current_mode(),
        "lang": lang,
    })
    events.publish({"type": "status", "state": "listening"})


def run_voice() -> None:
    active = False
    print("Voice system online")
    events.publish({"type": "status", "state": "idle"})

    for text, features in stream_recognition():
        text = text.strip()
        if not text:
            continue
        # Stamp so the proactive speaker won't talk over an active conversation.
        shared_state.LAST_USER_SPEECH = time.time()
        tone = classify(text, features)
        # Push the per-turn classification into the rolling history so the
        # agent's prompt sees the sustained conversational mode.
        mode = update_tone_history(tone)
        rms = features.get("rms", 0)
        lang = features.get("detected_lang", "en")
        is_owner = features.get("is_owner", True)
        speaker = features.get("speaker")
        score = features.get("speaker_score", 0)
        who = "owner" if is_owner else (f"{speaker}({score:.2f})" if speaker
                                        else f"guest({score:.2f})")
        print(f"[heard] ({tone}/{mode}/{lang}/{who} rms={rms:.0f}) {text}")
        events.publish({
            "type": "heard", "text": text, "tone": tone, "mode": mode,
            "rms": round(rms, 1), "active": active, "lang": lang,
            "is_owner": is_owner, "speaker": speaker,
        })

        if not active:
            remainder = detect_and_strip(text)
            if remainder is None:
                events.publish({"type": "status", "state": "idle"})
                continue
            active = True
            events.publish({"type": "wake", "active": True})
            if remainder:
                _handle_turn(remainder, tone=tone, lang=lang, is_owner=is_owner, speaker=speaker)
            else:
                events.publish({"type": "status", "state": "speaking"})
                speak("Yeah?")
                events.publish({"type": "status", "state": "listening"})
            continue

        if _is_sleep(text):
            active = False
            events.publish({"type": "wake", "active": False})
            events.publish({"type": "status", "state": "speaking"})
            speak("Talk soon.")
            events.publish({"type": "status", "state": "idle"})
            continue

        _handle_turn(text, tone=tone, lang=lang, is_owner=is_owner, speaker=speaker)
