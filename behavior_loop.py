import time
from memory import search


def proactive_thought_loop(queue):

    while True:

        context = search("user interests recent topics")

        if "robotics" in context:

            queue.append("You seem focused on robotics lately. Want to build something new?")

        time.sleep(30)