from voice.speech_to_text import listen_once
from voice.text_to_speech import speak
from main import run_chat
import time


def voice_loop():

    print("Voice companion active.")

    while True:

        user_text = listen_once()

        if not user_text:
            time.sleep(0.2)
            continue

        print(f"You said: {user_text}")

        if user_text.lower() in ["exit voice", "stop"]:
            speak("Voice mode stopped.")
            break

        response = run_chat(user_text)

        print(f"AI: {response}")

        speak(response)