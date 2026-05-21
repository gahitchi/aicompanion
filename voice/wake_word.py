from voice.streaming_mic import audio_stream
from voice.speech_to_text import listen_once


WAKE_WORDS = ["companion", "hey companion", "assistant", "ok companion"]


def detect_wake_word(text):

    text = text.lower()

    return any(w in text for w in WAKE_WORDS)


def wake_word_loop(trigger_queue):

    print("Wake word system active...")

    for _ in audio_stream():

        text = listen_once()

        if not text:
            continue

        print(f"[Heard]: {text}")

        if detect_wake_word(text):

            trigger_queue.append({
                "type": "wake_trigger",
                "text": text
            })

            print("Wake word detected → activating agent")