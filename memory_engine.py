from cluster_memory import add_memory
from memory import search
from reward_engine import get_score


def store_memory(text, embedding_func):

    importance = get_score(text)

    add_memory(text, embedding_func, importance)


def get_memory_summary():

    return search("summary", k=10)