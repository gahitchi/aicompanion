"""Full-system launcher.

Modes (selected via env / args):
  default          — tk window + voice + dashboard + tray (interactive desktop)
  --voice-only     — voice + dashboard, headless (best for systemd auto-start)
                     also: JADE_VOICE_ONLY=1
  --no-welcome     — skip the personality-flavored startup greeting

Every optional interface is guarded so a missing system package self-disables
that interface and the rest of the app keeps running.
"""
import argparse
import os
import threading
import time
import traceback

from autonomous_loop import autonomous_loop
from main import task_queue
from scheduler import scheduler_loop


def _start_thread(name, target, *args):
    """Spawn a daemon thread that logs and swallows exceptions from `target`."""
    def runner():
        try:
            target(*args)
        except Exception:
            print(f"[{name}] disabled:")
            traceback.print_exc()

    t = threading.Thread(target=runner, daemon=True, name=name)
    t.start()
    return t


def _run_server():
    import uvicorn

    from server import app
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


def _run_voice():
    from voice.conversation_controller import run_voice
    run_voice()


def _run_tray():
    from tray import run_tray
    run_tray()


def _run_tk():
    """Tkinter on the main thread. Closing the window or hitting tray Exit quits the app."""
    from ui.window import CompanionWindow
    from main import run_chat
    from shared_state import STOP_EVENT

    window = CompanionWindow(run_chat)

    def _poll_stop():
        if STOP_EVENT.is_set():
            window.root.quit()
        else:
            window.root.after(200, _poll_stop)

    def _on_close():
        STOP_EVENT.set()
        window.root.quit()

    window.root.protocol("WM_DELETE_WINDOW", _on_close)
    window.root.after(200, _poll_stop)
    window.run()


def _speak_welcome():
    """Generate a personality-flavored one-liner and speak it via Kokoro.

    Runs in a background thread so it doesn't block the launcher's main flow.
    Tries to load the LLM + TTS lazily — if either isn't ready yet, falls back
    to a small fixed greeting so the user at least knows she's up.
    """
    def _do_welcome():
        # Brief delay so the user actually hears the welcome AFTER models load.
        time.sleep(2.0)
        from voice.text_to_speech import speak
        try:
            from main import companion  # noqa: F401  — ensures models init in main flow
            from persona import get_persona_prompt
            persona_prompt = get_persona_prompt()
            # Run a memory consolidation pass first — non-blocking, fast when
            # skipped, surfaces follow-ups we can reference in the greeting.
            try:
                import memory_consolidator
                report = memory_consolidator.consolidate()
                if report.get("ok"):
                    print(f"[consolidator] {report}")
            except Exception as e:
                print(f"[consolidator] failed: {e}")

            followups = []
            try:
                from memory_consolidator import get_followups
                followups = get_followups()[:3]  # cap how much we feed in
            except Exception:
                pass

            extra = (
                "\n\nYou just booted up. Greet the user in one short, "
                "in-character line. Not 'how can I help' — just say hi as you."
            )
            if followups:
                extra += (
                    "\n\nOpen threads from last time you might naturally bring "
                    "up (only if it feels right — don't force it): "
                    + " | ".join(followups)
                )
            messages = [
                {"role": "system", "content": persona_prompt + extra},
                {"role": "user", "content": "(say hi, you just booted up)"},
            ]
            import llm
            greeting = llm.chat(messages, temperature=0.95).strip()
            if len(greeting) > 200:
                greeting = greeting[:200]
        except Exception as e:
            print(f"[welcome] LLM unavailable ({e}); using fallback")
            greeting = "Hey. I'm here."
        print(f"[welcome] {greeting}")
        try:
            speak(greeting)
        except Exception as e:
            print(f"[welcome] speak failed: {e}")

    threading.Thread(target=_do_welcome, daemon=True, name="welcome").start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--voice-only", action="store_true",
        default=os.environ.get("JADE_VOICE_ONLY") == "1",
        help="Run voice + dashboard only; no tk window, no tray. Best for systemd auto-start.",
    )
    parser.add_argument(
        "--no-welcome", action="store_true",
        default=os.environ.get("JADE_NO_WELCOME") == "1",
        help="Skip the spoken startup greeting.",
    )
    args = parser.parse_args()

    mode = "voice-only" if args.voice_only else "interactive"
    print(f"Companion launcher starting ({mode})...")

    _start_thread("autonomous", autonomous_loop, task_queue)
    _start_thread("scheduler", scheduler_loop, task_queue)
    _start_thread("server", _run_server)
    voice_thread = _start_thread("voice", _run_voice)

    if not args.voice_only:
        _start_thread("tray", _run_tray)

    if not args.no_welcome:
        _speak_welcome()

    if args.voice_only:
        # Headless: park on the voice thread until STOP_EVENT or KeyboardInterrupt.
        from shared_state import STOP_EVENT
        try:
            while not STOP_EVENT.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nShutting down.")
            STOP_EVENT.set()
        voice_thread.join(timeout=1.0)
        return

    try:
        _run_tk()
    except Exception:
        print("[tk] disabled:")
        traceback.print_exc()
        print("Tk failed; falling back to CLI.")
        from main import cli_loop
        cli_loop()

    from shared_state import STOP_EVENT
    STOP_EVENT.set()
    voice_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
