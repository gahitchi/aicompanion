from ui.window import CompanionWindow
from main import run_chat


def start_ui():

    def handler(user_input):
        return run_chat(user_input)

    app = CompanionWindow(handler)
    app.run()