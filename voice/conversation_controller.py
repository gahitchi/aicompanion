from voice.streaming_asr import stream_recognition
from voice.wake_engine import detect

from voice.text_to_speech import speak

from main import run_chat


ACTIVE = False


def run_voice():

    global ACTIVE

    print(
        "Voice system online"
    )

    for text in stream_recognition():

        print(
            f"[heard] {text}"
        )

        if not ACTIVE:

            if detect(text):

                ACTIVE = True

                speak(
                    "Listening"
                )

            continue

        if text in {

            "stop listening",
            "goodbye companion"

        }:

            ACTIVE = False

            speak(
                "Standing by"
            )

            continue

        response = run_chat(
            text
        )

        speak(response)