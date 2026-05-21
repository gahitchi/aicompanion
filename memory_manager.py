from memory import add, search
from user_model import update_user
from emotion import update_from_input
from episodic_memory import add_episode, retrieve_recent
from identity import update_from_interaction


def store_interaction(user, ai, emotion):

    # vector memory
    add(f"User: {user}")
    add(f"AI: {ai}")

    # short-term behavioral learning
    update_user(user)

    # emotional + episodic memory
    add_episode(user, ai, emotion)

    # LONG HORIZON IDENTITY UPDATE
    update_from_interaction(user, ai)


def retrieve_context(query):

    mem = search(query)
    episodes = retrieve_recent()

    episode_text = "\n".join(
        [f"{e['user']} -> {e['ai']}" for e in episodes]
    )

    return mem + "\n" + episode_text