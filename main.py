import threading
import time

from llm import chat
from persona import get_persona_prompt
from memory_manager import store_interaction, retrieve_context, process_input
from user_model import build_user_context
from state import history

from emotion import get_emotion_prompt
from identity import get_identity_prompt

from autonomous_loop import autonomous_loop
from scheduler import scheduler_loop


# --------------------------
# SHARED TASK QUEUE
# --------------------------
task_queue = []


# --------------------------
# CORE CHAT ENGINE
# --------------------------
def run_chat(user_input):

    emotion_state = process_input(user_input)

    memory = retrieve_context(user_input)
    user_ctx = build_user_context()

    prompt = f"""
{get_persona_prompt()}

{get_emotion_prompt()}

{get_identity_prompt()}

User context:
{user_ctx}

Memory:
{memory}

Conversation:
{history[-10:]}

User: {user_input}
"""

    response = chat(user_input, prompt)

    store_interaction(user_input, response, emotion_state)

    history.append(f"User: {user_input}")
    history.append(f"AI: {response}")

    return response


# --------------------------
# CLI LOOP (USER INTERFACE)
# --------------------------
def cli_loop():

    print("AI Companion online")

    while True:

        user_input = input("> ")

        if user_input.lower() in ["exit", "quit"]:
            break

        response = run_chat(user_input)

        print("\nAI:", response, "\n")


# --------------------------
# BACKGROUND SYSTEM STARTUP
# --------------------------
if __name__ == "__main__":

    # 1. autonomous reasoning loop
    threading.Thread(
        target=autonomous_loop,
        args=(task_queue,),
        daemon=True
    ).start()

    # 2. scheduler loop
    threading.Thread(
        target=scheduler_loop,
        args=(task_queue,),
        daemon=True
    ).start()

    # 3. CLI (main thread)
    cli_loop()