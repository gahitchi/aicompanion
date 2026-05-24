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
import events
from main import companion
from voice.streaming_asr import stream_recognition
from voice.text_to_speech import speak, speak_stream
from voice.tone import classify, update_tone_history, current_mode
from voice.wake_engine import detect_and_strip


SLEEP_PHRASES = {"stop listening", "goodbye companion", "go to sleep"}


def _is_sleep(text: str) -> bool:
    lo = text.strip().lower().strip(".,!?;: ")
    return lo in SLEEP_PHRASES


def _handle_turn(text: str, tone: str = "neutral", lang: str = "en",
                 is_owner: bool = True) -> None:
    """Run one user turn through the LLM and speak the reply, matching tone.

    Streams tokens straight into TTS so the first sentence plays while the
    LLM is still generating the rest. `is_owner` gates personal memory: when
    the speaker isn't the enrolled owner, the agent runs without their private
    context.
    """
    events.publish({"type": "status", "state": "thinking"})
    try:
        token_stream = companion.chat_stream(text, tone=tone, lang=lang, is_owner=is_owner)
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
        tone = classify(text, features)
        # Push the per-turn classification into the rolling history so the
        # agent's prompt sees the sustained conversational mode.
        mode = update_tone_history(tone)
        rms = features.get("rms", 0)
        lang = features.get("detected_lang", "en")
        is_owner = features.get("is_owner", True)
        who = "owner" if is_owner else f"guest({features.get('speaker_score', 0):.2f})"
        print(f"[heard] ({tone}/{mode}/{lang}/{who} rms={rms:.0f}) {text}")
        events.publish({
            "type": "heard", "text": text, "tone": tone, "mode": mode,
            "rms": round(rms, 1), "active": active, "lang": lang,
            "is_owner": is_owner,
        })

        if not active:
            remainder = detect_and_strip(text)
            if remainder is None:
                events.publish({"type": "status", "state": "idle"})
                continue
            active = True
            events.publish({"type": "wake", "active": True})
            if remainder:
                _handle_turn(remainder, tone=tone, lang=lang, is_owner=is_owner)
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

        _handle_turn(text, tone=tone, lang=lang, is_owner=is_owner)
