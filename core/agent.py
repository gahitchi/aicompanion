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
from persona import get_persona_prompt
from emotion import load as load_emotion, update_from_input as update_emotion
from identity import load as load_identity, update_from_interaction
from episodic_memory import add_episode, retrieve_recent
from user_model import update_user, build_user_context
from state import history
from tools import registry
from tools.filesystem import _Result as _ToolPending
from tools.safety import is_yes, is_no


MAX_AGENT_STEPS = 5
MAX_TOOLS_PER_TURN = 6  # safety cap so chat doesn't spin in a tool loop
HISTORY_TURNS = 8
EPISODIC_TURNS = 5
MEMORY_K = 3


def _system_prompt(extra: str = "", include_identity: bool = True) -> str:
    """Persona + live emotion + identity snapshot, plus optional appendix.

    `include_identity=False` drops the owner's identity overlay — used when the
    speaker isn't the recognized owner, so Jade doesn't reveal who they are.
    """
    identity = load_identity() if include_identity else None
    base = get_persona_prompt(emotion=load_emotion(), identity=identity)
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
                           is_owner: bool = True) -> list:
    """Build a chat-completion message list with retrieved memory and recent history.

    `tone` is the per-turn classification (soft/playful/neutral/focused/sad/angry).
    `lang` is the user's detected speech language (ISO short code). When non-en,
    a language-match instruction is appended to the system message.
    `is_owner` gates the owner's private context: when False (an unrecognized
    voice), no identity, memories, episodes, or chat history are loaded, and a
    guest guard is appended instead.
    """
    from voice.tone import TONE_DIRECTIVES, MODE_DIRECTIVES, current_mode

    context_block = []
    if is_owner:
        mems = memory.get_memories(user_input, k=MEMORY_K)
        episodes = retrieve_recent()[-EPISODIC_TURNS:]
        # Filter out episodes whose AI side looks like an old hallucinated tool
        # answer — code-fenced fake `ls` output, "[PROPOSED..." text, etc. These
        # poison new turns because the model copies the pattern.
        episodes = [
            e for e in episodes
            if "[PROPOSED" not in e.get("ai", "")
            and "```" not in e.get("ai", "")
        ]
        user_ctx = build_user_context()

        if user_ctx:
            context_block.append(user_ctx)
        if mems:
            context_block.append("Relevant memories:\n" + "\n".join(f"- {m}" for m in mems))
        if episodes:
            ep_text = "\n".join(f"  user: {e['user']}\n  you:  {e['ai']}" for e in episodes)
            context_block.append("Recent episodes:\n" + ep_text)
    else:
        context_block.append(_GUEST_GUARD)

    mode = current_mode()
    mode_directive = MODE_DIRECTIVES.get(mode, "")
    if mode_directive:
        context_block.append(f"Conversation mode: {mode}\n{mode_directive}")

    tone_directive = TONE_DIRECTIVES.get(tone, "")
    if tone_directive:
        context_block.append(f"User's current tone: {tone}\n{tone_directive}")

    if lang and lang != "en":
        lang_name = _LANG_NAME.get(lang, lang)
        context_block.append(
            f"LANGUAGE: The user spoke {lang_name}. Reply ENTIRELY in "
            f"{lang_name}. Do not mix in English, Chinese, or any other "
            f"language mid-reply. Stay in {lang_name} until they switch back."
        )

    system = _system_prompt("\n\n".join(context_block), include_identity=is_owner)

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
        # Detected language of the user's most recent utterance (ISO short
        # code: "en", "it", "es", ...). Used by the persona prompt to nudge
        # Jade into replying in the same language, and by TTS to pick a voice.
        self.last_lang: str = "en"

    def chat(self, user_input: str, tone: str = "neutral", lang: Optional[str] = None,
             is_owner: bool = True) -> str:
        # Drain pending confirmation if any.
        prefix = self._handle_pending(user_input)
        if prefix == "_consumed":
            # The user input WAS the yes/no — silent return; the tool already
            # ran and produced its observation, which we now ask the LLM to
            # summarize.
            user_input = "(continue from where you were)"
        emotion_state = update_emotion(user_input)
        if is_owner:
            update_user(user_input)

        if lang:
            self.last_lang = lang
        messages = _conversation_messages(user_input, tone=tone, lang=self.last_lang,
                                          is_owner=is_owner)
        if prefix and prefix != "_consumed":
            messages.append({"role": "system", "content": prefix})

        reply = self._chat_with_tools(messages, streaming=False)
        self._finalize_turn(user_input, reply, emotion_state, is_owner=is_owner)
        return reply

    def chat_stream(self, user_input: str, tone: str = "neutral", lang: Optional[str] = None,
                    is_owner: bool = True):
        """Generator: yields text deltas as the LLM produces them. Internally
        handles tool calls — if the LLM emits one, this generator runs it and
        keeps streaming the continuation. If the tool is CONFIRM tier,
        pending_action gets set and the LLM narrates what it's about to do.

        `is_owner=False` runs without the owner's private context and skips
        persistent personal writes (see _finalize_turn)."""
        prefix = self._handle_pending(user_input)
        if prefix == "_consumed":
            user_input = "(continue from where you were)"
        emotion_state = update_emotion(user_input)
        if is_owner:
            update_user(user_input)

        if lang:
            self.last_lang = lang
        messages = _conversation_messages(user_input, tone=tone, lang=self.last_lang,
                                          is_owner=is_owner)
        if prefix and prefix != "_consumed":
            messages.append({"role": "system", "content": prefix})

        parts = []
        for token in self._stream_with_tools(messages):
            parts.append(token)
            yield token

        reply = "".join(parts).strip()
        self._finalize_turn(user_input, reply, emotion_state, is_owner=is_owner)

    # ---------- internal: tool-call loop ----------------------------------

    def _chat_with_tools(self, messages: list, streaming: bool) -> str:
        """Non-streaming chat with tool support. Used by chat()."""
        tools = registry.tool_schemas()
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
        tools = registry.tool_schemas()
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
        result = registry.run(name, **(args if isinstance(args, dict) else {}))
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
            result = registry.run(action["tool"], _confirmed=True, **action["args"])
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
                       is_owner: bool = True) -> None:
        """Post-turn side effects: memory writes, episodic capture, identity update.

        For a guest (``is_owner=False``) we persist nothing — a stranger must not
        write into the owner's long-term memory, episodes, identity, or even the
        replayed chat history. The turn happens, then it's forgotten.
        """
        if not is_owner:
            return
        memory.save_memory(f"User said: {user_input}", kind="event")
        memory.save_memory(f"Companion replied: {reply}", kind="event")
        add_episode(user_input, reply, emotion_state)
        update_from_interaction(user_input, reply)
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
