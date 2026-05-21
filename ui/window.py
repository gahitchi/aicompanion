import tkinter as tk
from threading import Thread


class CompanionWindow:

    def __init__(self, on_send):

        self.root = tk.Tk()
        self.root.title("AI Companion")
        self.root.geometry("420x600")

        self.on_send = on_send

        self.chat_log = tk.Text(self.root, height=28, width=50)
        self.chat_log.pack()

        self.input_box = tk.Entry(self.root, width=40)
        self.input_box.pack()

        self.send_btn = tk.Button(self.root, text="Send", command=self.send)
        self.send_btn.pack()

    def send(self):

        text = self.input_box.get()
        self.input_box.delete(0, tk.END)

        self.chat_log.insert(tk.END, f"\nYou: {text}\n")

        def run():
            response = self.on_send(text)
            self.chat_log.insert(tk.END, f"AI: {response}\n")

        Thread(target=run, daemon=True).start()

    def run(self):
        self.root.mainloop()