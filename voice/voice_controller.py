from main import run_chat
from voice.text_to_speech import speak


def handle_voice_session(initial_text):

    # remove wake word
    cleaned = initial_text.lower()
    for w in ["companion", "hey companion", "ok companion", "assistant"]:
        cleaned = cleaned.replace(w, "")

    cleaned = cleaned.strip()

    if not cleaned:
        cleaned = "hello"

    response = run_chat(cleaned)

    speak(response)