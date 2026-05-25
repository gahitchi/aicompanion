"""The Companion agent — single entrypoint for both conversational chat and task execution.

Two modes:
- chat(user_input) -> str          # personality-driven reply with memory and state updates
- run_task(task) -> str            # ReAct loop: plan → tool → observe → ... → final answer
"""
import json
import re
from typing import Optional

import llm
import memory
import mood
import profiles
from persona import get_persona_prompt
from emotion import load as load_emotion, update_from_input as update_emotion
from episodic_memory import add_episode, retrieve_recent
from state import history
from tools import registry
from tools.filesystem import _Result as _ToolPending
from tools.safety import is_yes, is_no


MAX_AGENT_STEPS = 5
MAX_TOOLS_PER_TURN = 6  # safety cap so chat doesn't spin in a tool loop
HISTORY_TURNS = 8
EPISODIC_TURNS = 5
MEMORY_K = 3


def _system_prompt(extra: str = "", overrides: dict = None) -> str:
    """Persona (base principles + adjustable traits) + live emotion, plus appendix.

    `overrides` is the speaker's adjustable-trait dict from their profile, so the
    persona's DELIVERY adapts per user while the base principles stay fixed. The
    per-user knowledge/preferences ride in `extra` (the adaptation block built by
    _conversation_messages), not here.
    """
    base = get_persona_prompt(emotion=load_emotion(), overrides=overrides)
    return base + ("\n\n" + extra if extra else "")


# Appended to a guest's system prompt: warm, but no access to the owner's life.
_GUEST_GUARD = (
    "NOTE: You do NOT recognize this speaker's voice as your person (the owner "
    "you belong to). Be warm, friendly, and helpful as a fresh acquaintance, "
    "but do NOT share, confirm, or reference any personal details, memories, "
    "plans, projects, or private information about your owner — you have none "
    "loaded for this conversation anyway. If asked about your owner's private "
    "information, politely decline and keep things general."
)


_LANG_NAME = {
    "en": "English", "it": "Italian", "es": "Spanish", "fr": "French",
    "de": "German", "pt": "Portuguese",
}


def _conversation_messages(user_input: str, tone: str = "neutral", lang: str = "en",
                           is_owner: bool = True, speaker: str = None,
                           features: dict = None) -> list:
    """Build a chat-completion message list with retrieved memory and recent history.

    `tone` is the per-turn acoustic classification (drives TTS prosody on voice).
    `features` are the voice acoustics for this turn (None for typed chat).
    `lang` is the user's detected speech language (ISO short code). When non-en,
    a language-match instruction is appended to the system message.
    `is_owner` gates the owner's private context: when False (an unrecognized
    voice), no identity, memories, episodes, or chat history are loaded.
    `speaker` is the recognized name of a known non-owner (household member), so
    Jade can greet them by name without exposing the owner's private memory.
    """
    from voice.tone import TONE_DIRECTIVES

    # Resolve the speaker to a profile identity. Owner → "owner"; a recognized
    # household member → their name; an unknown guest → None (no profile, no
    # trace). Stash it so tools (tools/preferences.py) write to the right person.
    person = profiles.OWNER if is_owner else (speaker or None)
    profiles.set_current(person)
    trait_overrides = profiles.overrides(person) if person else None

    context_block = []
    if is_owner:
        # Semantic long-term memory (Chroma) stays owner-only.
        mems = memory.get_memories(user_input, k=MEMORY_K)
        if mems:
            context_block.append("Relevant memories:\n" + "\n".join(f"- {m}" for m in mems))
    elif speaker:
        context_block.append(
            f"NOTE: The current speaker is {speaker}, a member of the household "
            f"you recognize by voice — but NOT your owner. Greet and address them "
            f"by name and be warm and helpful, but do NOT share, confirm, or "
            f"reference your owner's private memories, plans, or personal details."
        )
    else:
        context_block.append(_GUEST_GUARD)

    # Recent episodes are per-person — never replay one person's history to
    # another. Filter out old hallucinated tool answers (code-fenced fake `ls`
    # output, "[PROPOSED..." text) that otherwise poison new turns.
    if person:
        episodes = [
            e for e in retrieve_recent(person=person, n=EPISODIC_TURNS)
            if "[PROPOSED" not in e.get("ai", "") and "```" not in e.get("ai", "")
        ]
        if episodes:
            ep_text = "\n".join(f"  user: {e['user']}\n  you:  {e['ai']}" for e in episodes)
            context_block.append("Recent episodes:\n" + ep_text)

    # Ad-personam adaptation: who this person is + how they like Jade to be,
    # fenced by the principle boundary. Empty for guests / until something's
    # learned. (Their trait dials are applied separately via `trait_overrides`.)
    if person:
        adapt = profiles.adaptation_prompt(person)
        if adapt:
            context_block.append(adapt)

    # Sticky per-person mood — the sustained conversational register. Advances
    # once per turn (signal switches it; silence holds then decays). Guests get
    # a transient, un-persisted read so a passing register still lands.
    if person:
        mood_now = mood.update(person, user_input, features)
    else:
        mood_now = mood.signal_from_text(user_input, features) or mood.NEUTRAL
    mood_directive = mood.MOOD_DIRECTIVES.get(mood_now, "")
    if mood_directive:
        context_block.append(f"Current mood: {mood_now}\n{mood_directive}")

    # Per-turn acoustic tone (voice only) layers nuance under the sticky mood.
    tone_directive = TONE_DIRECTIVES.get(tone, "")
    if tone_directive:
        context_block.append(f"How they sound right now: {tone}\n{tone_directive}")

    if lang and lang != "en":
        lang_name = _LANG_NAME.get(lang, lang)
        context_block.append(
            f"LANGUAGE: The user spoke {lang_name}. Reply ENTIRELY in "
            f"{lang_name}. Do not mix in English, Chinese, or any other "
            f"language mid-reply. Stay in {lang_name} until they switch back."
        )

    # Transient game / roleplay mode (set by tools/modes.py) layered on top of
    # the persona for this turn. Cleared on its own timeout or by the stop tools.
    from session import active_instruction
    mode_text = active_instruction()
    if mode_text:
        context_block.append(mode_text)

    system = _system_prompt("\n\n".join(context_block), overrides=trait_overrides)

    messages = [{"role": "system", "content": system}]

    # Recent history is the owner's conversation — never replay it for a guest.
    if is_owner:
        for turn in history[-HISTORY_TURNS * 2:]:
            if turn.startswith("User: "):
                messages.append({"role": "user", "content": turn[6:]})
            elif turn.startswith("AI: "):
                messages.append({"role": "assistant", "content": turn[4:]})

    messages.append({"role": "user", "content": user_input})
    return messages


class Companion:
    """One Companion instance per process. Stateless across calls — state lives in
    json files (emotion, identity, episodic) and Chroma (memory). The single
    in-memory state is `pending_action`, which holds a tool call awaiting the
    user's yes/no confirmation."""

    def __init__(self):
        # {tool, args, description} when a CONFIRM-tier action awaits user OK.
        self.pending_action: Optional[dict] = None
        # Whether the current turn's speaker is the recognized owner. Gates
        # owner-only tools (email, calendar) so they're neither offered to nor
        # runnable by a household member / guest. Set per-turn in chat/chat_stream.
        self._turn_is_owner: bool = True
        # Detected language of the user's most recent utterance (ISO short
        # code: "en", "it", "es", ...). Used by the persona prompt to nudge
        # Jade into replying in the same language, and by TTS to pick a voice.
        self.last_lang: str = "en"

    def chat(self, user_input: str, tone: str = "neutral", lang: Optional[str] = None,
             is_owner: bool = True, speaker: Optional[str] = None,
             features: Optional[dict] = None) -> str:
        self._turn_is_owner = is_owner
        # Drain pending confirmation if any.
        prefix = self._handle_pending(user_input)
        if prefix == "_consumed":
            # The user input WAS the yes/no — silent return; the tool already
            # ran and produced its observation, which we now ask the LLM to
            # summarize.
            user_input = "(continue from where you were)"
        emotion_state = update_emotion(user_input)

        if lang:
            self.last_lang = lang
        messages = _conversation_messages(user_input, tone=tone, lang=self.last_lang,
                                          is_owner=is_owner, speaker=speaker, features=features)
        if prefix and prefix != "_consumed":
            messages.append({"role": "system", "content": prefix})

        reply = self._chat_with_tools(messages, streaming=False)
        self._finalize_turn(user_input, reply, emotion_state, is_owner=is_owner, speaker=speaker)
        return reply

    def chat_stream(self, user_input: str, tone: str = "neutral", lang: Optional[str] = None,
                    is_owner: bool = True, speaker: Optional[str] = None,
                    features: Optional[dict] = None):
        """Generator: yields text deltas as the LLM produces them. Internally
        handles tool calls — if the LLM emits one, this generator runs it and
        keeps streaming the continuation. If the tool is CONFIRM tier,
        pending_action gets set and the LLM narrates what it's about to do.

        `is_owner=False` runs without the owner's private context and skips
        persistent personal writes (see _finalize_turn). `speaker` is the
        recognized name of a known non-owner."""
        self._turn_is_owner = is_owner
        prefix = self._handle_pending(user_input)
        if prefix == "_consumed":
            user_input = "(continue from where you were)"
        emotion_state = update_emotion(user_input)

        if lang:
            self.last_lang = lang
        messages = _conversation_messages(user_input, tone=tone, lang=self.last_lang,
                                          is_owner=is_owner, speaker=speaker, features=features)
        if prefix and prefix != "_consumed":
            messages.append({"role": "system", "content": prefix})

        parts = []
        for token in self._stream_with_tools(messages):
            parts.append(token)
            yield token

        reply = "".join(parts).strip()
        self._finalize_turn(user_input, reply, emotion_state, is_owner=is_owner, speaker=speaker)

    # ---------- internal: tool-call loop ----------------------------------

    def _chat_with_tools(self, messages: list, streaming: bool) -> str:
        """Non-streaming chat with tool support. Used by chat()."""
        tools = registry.tool_schemas(owner=self._turn_is_owner)
        for _step in range(MAX_TOOLS_PER_TURN + 1):
            msg = llm.chat(messages, tools=tools)
            text = (msg.content or "").strip() if msg else ""
            calls = getattr(msg, "tool_calls", None) or []
            if not calls:
                return text
            # Persist the assistant turn that requested tools.
            messages.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name,
                                  "arguments": c.function.arguments}}
                    for c in calls
                ],
            })
            confirm_set = False
            for c in calls:
                obs = self._run_tool(c.function.name, c.function.arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": c.id,
                    "name": c.function.name,
                    "content": obs if isinstance(obs, str) else obs.description,
                })
                if isinstance(obs, _ToolPending):
                    confirm_set = True
            if confirm_set:
                # The tool was NOT executed — only proposed. Tell the LLM
                # explicitly to ask, not announce. Most small-LLM confusion
                # comes from this exact misread, so the instruction is blunt.
                messages.append({
                    "role": "system",
                    "content": (
                        "IMPORTANT: the tool above has NOT been executed yet — it "
                        "is awaiting the user's permission. Do NOT say you did "
                        "it. Briefly tell the user what you're proposing to do "
                        "and ask for their go-ahead, then stop. Do not call any "
                        "more tools this turn."
                    ),
                })
                final = llm.chat(messages)  # no tools — pure text
                return final.strip() if final else "Want me to go ahead?"
        return "(hit the tool-call cap; stopping to avoid a loop.)"

    def _stream_with_tools(self, messages: list):
        """Streaming chat with tool support. Used by chat_stream(). Yields text."""
        tools = registry.tool_schemas(owner=self._turn_is_owner)
        for _step in range(MAX_TOOLS_PER_TURN + 1):
            text_buf = []
            tool_calls = None
            for item in llm.chat_stream(messages, tools=tools):
                if isinstance(item, tuple):
                    kind, payload = item
                    if kind == "text":
                        text_buf.append(payload)
                        yield payload
                    elif kind == "tool_calls":
                        tool_calls = payload
                else:
                    # back-compat path (no tools)
                    text_buf.append(item)
                    yield item
            if not tool_calls:
                return
            messages.append({
                "role": "assistant",
                "content": "".join(text_buf) or None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["args"]}}
                    for tc in tool_calls
                ],
            })
            confirm_set = False
            for tc in tool_calls:
                obs = self._run_tool(tc["name"], tc["args"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "content": obs if isinstance(obs, str) else obs.description,
                })
                if isinstance(obs, _ToolPending):
                    confirm_set = True
            if confirm_set:
                # See _chat_with_tools for the rationale on this blunt phrasing.
                messages.append({
                    "role": "system",
                    "content": (
                        "IMPORTANT: the tool above has NOT been executed yet — it "
                        "is awaiting the user's permission. Do NOT say you did "
                        "it. Briefly tell the user what you're proposing to do "
                        "and ask for their go-ahead, then stop. Do not call any "
                        "more tools this turn."
                    ),
                })
                for token in llm.chat_stream(messages):
                    yield token
                return
        # Hit the cap.
        yield " ...I'm getting stuck in a loop, going to stop here."

    def _run_tool(self, name: str, args_json):
        """Decode args, call the registry, capture pending state if any."""
        try:
            args = json.loads(args_json) if isinstance(args_json, str) else (args_json or {})
        except json.JSONDecodeError:
            return f"tool_error: arguments not valid JSON: {args_json!r}"
        result = registry.run(name, owner=self._turn_is_owner,
                              **(args if isinstance(args, dict) else {}))
        if isinstance(result, _ToolPending):
            self.pending_action = {
                "tool": result.tool or name,
                "args": result.args or args,
                "description": result.description,
            }
        return result

    def _handle_pending(self, user_input: str) -> str:
        """If there's a pending action and the user said yes/no, resolve it.

        Returns:
          ""           — no pending action; proceed normally
          "_consumed"  — user input was the confirmation; tool ran or was cancelled
          "<text>"     — a system-message prefix the LLM should see this turn
        """
        if not self.pending_action:
            return ""
        action = self.pending_action
        if is_yes(user_input):
            result = registry.run(action["tool"], _confirmed=True,
                                  owner=self._turn_is_owner, **action["args"])
            self.pending_action = None
            preview = result if isinstance(result, str) else "(done)"
            return (
                f"IMPORTANT: you JUST executed `{action['tool']}` — it is DONE. "
                f"The result was: {preview}. Tell the user the action completed "
                f"in your own voice (one short sentence). DO NOT call "
                f"`{action['tool']}` again — it already ran. Do not call any "
                f"tools on this turn."
            )
        if is_no(user_input):
            self.pending_action = None
            return (
                f"The user declined `{action['tool']}`. Acknowledge briefly and "
                f"move on. Do not call any tools on this turn."
            )
        # User moved on — drop the pending action.
        self.pending_action = None
        return ""

    def _finalize_turn(self, user_input: str, reply: str, emotion_state,
                       is_owner: bool = True, speaker: Optional[str] = None) -> None:
        """Post-turn side effects: memory writes, episodic capture, identity update.

        Only the owner writes to long-term memory / episodes / identity / replayed
        history — a non-owner must never pollute the owner's record. A recognized
        household member just gets their last-seen stamp bumped; an unknown guest
        leaves no trace at all.
        """
        if not is_owner:
            # A recognized household member: bump THEIR profile (so Jade adapts
            # to them too), stamp last-seen — but never write the owner's private
            # memory/episodes/history. An unknown guest leaves no trace at all.
            if speaker:
                import people
                people.record_seen(speaker)
                profiles.record_interaction(speaker, user_input, reply)
                add_episode(user_input, reply, emotion_state, person=speaker)
            return
        memory.save_memory(f"User said: {user_input}", kind="event")
        memory.save_memory(f"Companion replied: {reply}", kind="event")
        add_episode(user_input, reply, emotion_state, person=profiles.OWNER)
        profiles.record_interaction(profiles.OWNER, user_input, reply)
        history.append(f"User: {user_input}")
        history.append(f"AI: {reply}")

    def run_task(self, task: str, max_steps: int = MAX_AGENT_STEPS) -> str:
        """ReAct-style execution. The model emits JSON each step; we run tools and feed
        results back until it emits a final answer or we hit the step cap."""
        tool_spec = "\n".join(f"- {name}: {sig}" for name, sig in registry.describe())

        protocol = f"""
You are now in agent mode. Solve the user's task by issuing tool calls.

Available tools:
{tool_spec}

Response protocol — every reply MUST be ONE JSON object, nothing else:
  {{"type": "tool", "tool": "<tool_name>", "args": {{...}}}}
or, when the task is complete:
  {{"type": "final", "content": "<your answer>"}}

Rules:
- One tool call per turn. Wait for the observation before issuing the next.
- Tool args must be a JSON object whose keys match the tool signature.
- Stop and emit "final" as soon as you have enough information. Don't loop unnecessarily.
- Stay in character (Companion's voice) in the final answer.
"""

        messages = [
            {"role": "system", "content": _system_prompt(protocol)},
            {"role": "user", "content": f"Task: {task}"},
        ]

        for step in range(max_steps):
            raw = llm.chat(
                messages,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            messages.append({"role": "assistant", "content": raw})

            parsed = _extract_json(raw)
            if parsed is None:
                messages.append({"role": "user", "content": "That wasn't valid JSON. Reply with exactly one JSON object as specified."})
                continue

            kind = parsed.get("type")
            if kind == "final":
                final = parsed.get("content", "").strip()
                self._record_task(task, final)
                return final

            if kind == "tool":
                name = parsed.get("tool", "")
                args = parsed.get("args", {}) or {}
                observation = registry.run(name, **args) if isinstance(args, dict) else "tool_error: args must be an object"
                observation_str = str(observation)
                if len(observation_str) > 2000:
                    observation_str = observation_str[:2000] + "\n...(truncated)"
                messages.append({"role": "user", "content": f"Observation: {observation_str}"})
                continue

            messages.append({"role": "user", "content": "Unknown type. Use 'tool' or 'final'."})

        fallback = f"Hit the {max_steps}-step cap without a final answer."
        self._record_task(task, fallback)
        return fallback

    def _record_task(self, task: str, result: str) -> None:
        memory.save_memory(f"Task: {task}\nResult: {result}", kind="task")


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _escape_string_newlines(s: str) -> str:
    """Inside double-quoted JSON string literals, escape raw \\n / \\r / \\t.

    Tracks escape state so we don't double-escape a `\\n` that was already escaped.
    Used as a fallback when the model emits a JSON-looking blob with literal
    newlines inside `content` strings.
    """
    out = []
    in_string = False
    escape_next = False
    for ch in s:
        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch)
            continue
        if escape_next:
            out.append(ch)
            escape_next = False
        elif ch == "\\":
            out.append(ch)
            escape_next = True
        elif ch == '"':
            in_string = False
            out.append(ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


def _extract_json(text: str) -> Optional[dict]:
    """Tolerant JSON extraction — strips code fences, finds first {...} block,
    falls back to escaping unescaped newlines inside string literals."""
    stripped = text.strip().strip("`")
    if stripped.startswith("json"):
        stripped = stripped[4:].lstrip()

    for candidate in (stripped, None):
        if candidate is None:
            m = _JSON_BLOCK.search(text)
            if not m:
                continue
            candidate = m.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            try:
                return json.loads(_escape_string_newlines(candidate))
            except json.JSONDecodeError:
                continue
    return None
