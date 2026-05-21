import threading

from ui.app import start_ui

from tray import run_tray

from autonomous_loop import autonomous_loop
from scheduler import scheduler_loop

from voice.conversation_controller import run_voice

from main import task_queue


if __name__ == "__main__":

    threading.Thread(
        target=autonomous_loop,
        args=(task_queue,),
        daemon=True
    ).start()

    threading.Thread(
        target=scheduler_loop,
        args=(task_queue,),
        daemon=True
    ).start()

    threading.Thread(
        target=run_voice,
        daemon=True
    ).start()

    threading.Thread(
        target=run_tray,
        daemon=True
    ).start()

    start_ui()