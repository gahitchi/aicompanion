import time
from memory.gnn_memory import retrieve_top_k
from rl.bandit import choose_action, update


def cognition_cycle(queue):

    while True:

        state = "default"

        top_mem = retrieve_top_k(3)

        actions = ["explore", "exploit", "optimize"]

        action = choose_action(state, actions)

        queue.append(action)

        reward = len(top_mem)

        update(state, action, reward)

        time.sleep(5)