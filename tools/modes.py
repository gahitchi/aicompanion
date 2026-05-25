"""Playful session modes — voice games and roleplay.

Both set a transient instruction in `session` that core/agent.py layers onto the
system prompt each turn; the start tools return a short cue the LLM turns into an
in-character opener, and the injected instruction drives every turn after. The
stop tools clear it (a 30-min idle clears it too — see session.py).

SAFE and not owner-only: anyone in the house can play a game or ask her to do a
voice. Because the mode is global to the one device, whoever starts it sets it for
the next speaker as well — fine for a single household companion.
"""
import session

# game kind -> how to host it (appended to the persona, so she stays herself
# while running the game). Keep turns short and spoken; no walls of text.
_GAMES = {
    "20questions": (
        "GAME — 20 Questions: think of a person, place, or thing and keep it "
        "secret. Tell the user you've got something, and have them ask up to 20 "
        "yes/no questions to guess it. Answer honestly and briefly, count the "
        "questions, and react with personality. If they'd rather YOU guess, do "
        "the opposite and ask the questions."),
    "trivia": (
        "GAME — Trivia: ask the user fun trivia questions one at a time, wait for "
        "each answer, say if they're right (with the answer), keep score, and "
        "keep it light. Vary the topics."),
    "riddles": (
        "GAME — Riddles: pose a riddle, let the user guess, give a gentle hint if "
        "they're stuck, then reveal. One riddle at a time."),
    "wordchain": (
        "GAME — Word chain: each player says a word starting with the last letter "
        "of the previous word. Take turns, no repeats, keep it quick and fun."),
    "wouldyourather": (
        "GAME — Would You Rather: offer two interesting options, let the user "
        "pick, react to their choice, then offer another. Keep them playful."),
}

_ALIASES = {
    "20 questions": "20questions", "twenty questions": "20questions", "20q": "20questions",
    "word chain": "wordchain", "word association": "wordchain",
    "would you rather": "wouldyourather", "riddle": "riddles", "quiz": "trivia",
}

_HOST_RULES = ("Stay fully in character as Jade while hosting. Keep each turn "
               "short and spoken — no markdown or lists. If the user clearly "
               "wants to stop or changes the subject, call end_game and drop it "
               "naturally.")


def start_game(kind: str = "") -> str:
    """Start a voice game. kind: 20questions, trivia, riddles, wordchain, or
    wouldyourather. Leave blank to let Jade pick or offer a choice."""
    k = _ALIASES.get(kind.strip().lower(), kind.strip().lower().replace(" ", ""))
    if k in _GAMES:
        session.set_mode("game", _GAMES[k] + "\n" + _HOST_RULES, k)
        return f"[game on: {k}] Kick it off in character — give a quick intro and your first move."
    # No / unknown kind → offer the menu, no mode set yet.
    return ("Ask the user which game they'd like — 20 Questions, trivia, riddles, "
            "word chain, or would-you-rather — then call start_game with their pick.")


def end_game() -> str:
    """Stop the current game and return to normal conversation."""
    was = session.active()
    session.clear_mode()
    if was and was.get("kind") == "game":
        return "[game over] Wrap it up warmly and go back to being yourself."
    return "No game is running right now."


def roleplay_as(character: str) -> str:
    """Temporarily take on a character or speaking style (e.g. 'a noir detective',
    'a pirate', 'Shakespeare'). Stays in character until told to stop."""
    character = (character or "").strip()
    if not character:
        return "Who would you like me to be?"
    instruction = (
        f"ROLEPLAY: Take on the voice, manner, and flair of {character}. Commit to "
        f"it and have fun, but keep it light and safe, and keep your underlying "
        f"judgment as Jade. Stay in character until the user asks you to stop or "
        f"be yourself — then call stop_roleplay.")
    session.set_mode("roleplay", instruction, character)
    return f"[roleplay: {character}] Slip into character and greet them as {character}."


def stop_roleplay() -> str:
    """Drop the current character and go back to being Jade."""
    was = session.active()
    session.clear_mode()
    if was and was.get("kind") == "roleplay":
        return "[roleplay off] Step out of character and return to being yourself."
    return "I'm already just myself."
