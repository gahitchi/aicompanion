"""Entry point for CLI chat. The companion class lives in core.agent."""
import threading

from core.agent import Companion
from autonomous_loop import autonomous_loop
from scheduler import scheduler_loop


task_queue = []
companion = Companion()


def run_chat(user_input: str) -> str:
    """Thin shim kept for backward compatibility with UI/voice modules."""
    return companion.chat(user_input)


def cli_loop():
    print("Companion online. Type 'quit' to exit, 'agent: <task>' to run agent mode.\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        if user_input.lower().startswith("agent:"):
            task = user_input[6:].strip()
            print("\n[agent mode]\n")
            result = companion.run_task(task)
            print(f"\nResult:\n{result}\n")
            continue

        try:
            response = companion.chat(user_input)
        except Exception as e:
            print(f"\n[error] {e}\n")
            continue

        print(f"\nCompanion: {response}\n")


if __name__ == "__main__":
    threading.Thread(target=autonomous_loop, args=(task_queue,), daemon=True).start()
    threading.Thread(target=scheduler_loop, args=(task_queue,), daemon=True).start()
    cli_loop()
