"""Single LLM client for the Companion. OpenAI-compatible Ollama at localhost:11434."""
import envconfig  # noqa: F401  — load .env before reading OLLAMA_* below
import json
import os
import re
import uuid

from openai import OpenAI

# 3b is the default because the GPU only fits one big model at a time and we
# want Whisper on CUDA (otherwise ASR latency goes from ~150ms to ~4-8s).
# 3b is noticeably less smart and more repetitive — for a sharper Companion,
# set OLLAMA_MODEL to a 7-8b model (accept Whisper falling back to CPU, ~2-3s).
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct")
BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def _envf(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


# Sampling defaults tuned to reduce small-LLM repetition:
# - temperature 0.85 gives more variety than 0.7 without going incoherent
# - frequency_penalty discourages repeating the same tokens
# - presence_penalty discourages re-circling the same topics
# Override per-call or via env.
CHAT_TEMPERATURE = _envf("CHAT_TEMPERATURE", 0.85)
CHAT_FREQ_PENALTY = _envf("CHAT_FREQ_PENALTY", 0.5)
CHAT_PRES_PENALTY = _envf("CHAT_PRES_PENALTY", 0.5)

client = OpenAI(base_url=BASE_URL, api_key="ollama")


# Some Ollama models (notably the huihui_ai/qwen2.5-abliterate variants) emit
# tool calls as text through the OpenAI-compat endpoint instead of a structured
# tool_calls array. The text looks like: `brtc {"name": "X", "arguments": {}}`
# or `<tool_call>{"name": "X", ...}</tool_call>` or bare `{"name": "X", ...}`.
# This fallback parses such text into a synthetic _SyntheticToolCall list so the
# rest of the pipeline can treat it identically to a proper tool_calls response.

# Recognized text-fallback formats:
#   brtc {"name": "X", "arguments": {...}}
#   <tool_call>{"name": "X", "arguments": {...}}</tool_call>
#   {"name": "X", "arguments": {...}}
#   $toolname                         (no args)
#   $toolname({"key": "val"})         (with args)
#   toolname()                        (function-call style; abliterated models)
#   toolname({"key": "val"})          (function-call style with args)
_TOOL_JSON_PAT = re.compile(
    r'^\s*(?:brtc\s+|<tool_call>\s*)?(\{.*?\})(?:\s*</tool_call>)?\s*$', re.DOTALL)
_TOOL_DOLLAR_PAT = re.compile(
    r'^\s*\$(\w+)\s*(?:\(\s*(\{.*?\})\s*\))?\s*$', re.DOTALL)
_TOOL_FNCALL_PAT = re.compile(
    r'^\s*(\w+)\s*\(\s*(\{.*?\})?\s*\)\s*$', re.DOTALL)
# `tool_name {"key": "val"}` — name followed by a bare JSON args object.
_TOOL_NAMEJSON_PAT = re.compile(
    r'^\s*(\w+)\s+(\{.*\})\s*$', re.DOTALL)
# Bare `tool_name` — only matches if name is in registry.
_TOOL_BARE_PAT = re.compile(r'^\s*(\w+)\s*$')


def _known_tool_names():
    """Best-effort registry lookup. Cached. Returns set or empty on failure."""
    if not hasattr(_known_tool_names, "_cache"):
        try:
            from tools import registry  # late import; registry doesn't import llm
            _known_tool_names._cache = set(registry.TOOLS.keys())
        except Exception:
            _known_tool_names._cache = set()
    return _known_tool_names._cache


class _SyntheticFn:
    __slots__ = ("name", "arguments")
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _SyntheticToolCall:
    __slots__ = ("id", "function")
    def __init__(self, name, arguments):
        self.id = f"call_synth_{uuid.uuid4().hex[:8]}"
        self.function = _SyntheticFn(name, arguments)


def _looks_like_tool_text(text: str) -> bool:
    """Cheap predicate — does this content look like a text-fallback tool call?"""
    if not text:
        return False
    t = text.lstrip()
    if (t.startswith("$") or t.startswith("brtc ") or t.startswith("<tool_call>")
            or (t.startswith("{") and '"name"' in t[:120])):
        return True
    # Strict patterns: toolname(...), toolname {...}, bare toolname — name must
    # be a registered tool to count.
    known = _known_tool_names()
    for pat in (_TOOL_FNCALL_PAT, _TOOL_NAMEJSON_PAT, _TOOL_BARE_PAT):
        m = pat.match(t)
        if m and m.group(1).lower() in known:
            return True
    return False


def _parse_text_fallback_tool_calls(content: str):
    """Parse text-mode tool calls into a list of _SyntheticToolCall.

    Returns None if the content doesn't look like a tool call.
    Returns a list (possibly multiple calls separated by whitespace).
    """
    if not content:
        return None
    text = content.strip()

    # $toolname / $toolname({...})
    m = _TOOL_DOLLAR_PAT.match(text)
    if m:
        name = m.group(1)
        args_json = m.group(2) or "{}"
        try:
            json.loads(args_json)
        except json.JSONDecodeError:
            args_json = "{}"
        return [_SyntheticToolCall(name, args_json)]

    # toolname()/toolname({...}) — only if the name is a known tool.
    m = _TOOL_FNCALL_PAT.match(text)
    if m:
        name = m.group(1).lower()
        if name in _known_tool_names():
            args_json = m.group(2) or "{}"
            try:
                json.loads(args_json)
            except json.JSONDecodeError:
                args_json = "{}"
            return [_SyntheticToolCall(name, args_json)]

    # `toolname {"key": "val"}` — name + space + JSON object.
    m = _TOOL_NAMEJSON_PAT.match(text)
    if m and m.group(1).lower() in _known_tool_names():
        try:
            obj = json.loads(m.group(2))
            if isinstance(obj, dict):
                return [_SyntheticToolCall(m.group(1).lower(), json.dumps(obj))]
        except json.JSONDecodeError:
            pass

    # Bare `toolname` — only if a known tool. Risky on common words so we
    # require it match a registered tool exactly.
    m = _TOOL_BARE_PAT.match(text)
    if m and m.group(1).lower() in _known_tool_names():
        return [_SyntheticToolCall(m.group(1).lower(), "{}")]

    if "{" not in text or '"name"' not in text:
        return None

    # JSON object with name+arguments, possibly wrapped in brtc/<tool_call>
    m = _TOOL_JSON_PAT.match(text)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "name" in obj:
                args = obj.get("arguments", obj.get("parameters", {}))
                if isinstance(args, dict):
                    args = json.dumps(args)
                return [_SyntheticToolCall(obj["name"], args)]
        except json.JSONDecodeError:
            pass

    # Best-effort: scan for one or more JSON objects with "name". Handles
    # models that emit multiple back-to-back calls.
    calls = []
    for match in re.finditer(r'\{[^{}]*"name"\s*:\s*"[^"]+"[^{}]*\}', text):
        try:
            obj = json.loads(match.group(0))
            if "name" in obj:
                args = obj.get("arguments", obj.get("parameters", {}))
                if isinstance(args, dict):
                    args = json.dumps(args)
                calls.append(_SyntheticToolCall(obj["name"], args))
        except json.JSONDecodeError:
            continue
    return calls or None


def _build_kwargs(messages, temperature, model, response_format,
                  frequency_penalty, presence_penalty, tools=None, stream=False):
    kwargs = {
        "model": model or MODEL,
        "messages": messages,
        "temperature": temperature,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    if tools:
        kwargs["tools"] = tools
    if stream:
        kwargs["stream"] = True
    return kwargs


def chat(messages, temperature=None, model=None, response_format=None,
         frequency_penalty=None, presence_penalty=None, tools=None):
    """Chat-completion call. `messages` is a list of {role, content} dicts.

    Pass response_format={"type": "json_object"} to constrain JSON output.
    Pass tools=[...] (OpenAI tool-schemas) to enable function calling — the
    returned object will be the raw `message` (has .content and .tool_calls).
    """
    if temperature is None:
        temperature = CHAT_TEMPERATURE
    if frequency_penalty is None:
        frequency_penalty = CHAT_FREQ_PENALTY
    if presence_penalty is None:
        presence_penalty = CHAT_PRES_PENALTY
    kwargs = _build_kwargs(messages, temperature, model, response_format,
                           frequency_penalty, presence_penalty, tools=tools)
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    if tools is not None:
        # If the model didn't emit structured tool_calls but the content looks
        # like a tool-call payload (abliterated/uncensored variants do this),
        # synthesize tool_calls so the caller doesn't have to know the difference.
        if not getattr(msg, "tool_calls", None):
            synth = _parse_text_fallback_tool_calls(msg.content or "")
            if synth:
                msg.tool_calls = synth
                msg.content = ""
        return msg  # caller inspects .content and .tool_calls
    return (msg.content or "").strip()


def chat_simple(prompt, system="", temperature=None, model=None):
    """One-shot helper: system + user prompt → string reply."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(messages, temperature=temperature, model=model)


def chat_stream(messages, temperature=None, model=None,
                frequency_penalty=None, presence_penalty=None, tools=None):
    """Yield items from the LLM as they're generated.

    Without `tools`: yields content delta strings (back-compat).
    With `tools=[...]`: yields tuples of:
      ("text", str_delta) for each text chunk
      ("tool_calls", [...]) once, at the end of the stream, if any tool calls
      came through (full accumulated list).
    """
    if temperature is None:
        temperature = CHAT_TEMPERATURE
    if frequency_penalty is None:
        frequency_penalty = CHAT_FREQ_PENALTY
    if presence_penalty is None:
        presence_penalty = CHAT_PRES_PENALTY
    kwargs = _build_kwargs(messages, temperature, model, None,
                           frequency_penalty, presence_penalty,
                           tools=tools, stream=True)
    stream = client.chat.completions.create(**kwargs)

    if not tools:
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
        return

    # Tool-aware streaming. We buffer the first ~150 chars of text to detect
    # text-fallback tool calls (some models like the abliterated qwen variants
    # emit tool calls as plain text through OpenAI-compat). If the buffer looks
    # like a tool call, we treat all subsequent text as tool-call payload.
    # Otherwise we flush the buffer and resume normal text streaming.
    pending_calls = {}  # index → {"id": ..., "name": ..., "args": ""}
    text_buffer = ""
    fallback_mode = None  # None=undecided, True=text-is-tool-call, False=normal text
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                slot = pending_calls.setdefault(idx, {"id": None, "name": None, "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function.arguments:
                        slot["args"] += tc.function.arguments
        if delta.content:
            if fallback_mode is False:
                yield ("text", delta.content)
            else:
                text_buffer += delta.content
                # Detect early — even a single $ at the start is enough.
                stripped = text_buffer.lstrip()
                if fallback_mode is None:
                    if not stripped:
                        continue
                    # Definitive yes from a leading $
                    if stripped.startswith("$"):
                        fallback_mode = True
                    # Need more text to decide for JSON-like formats
                    elif _looks_like_tool_text(stripped) and len(stripped) >= 40:
                        fallback_mode = True
                    elif not stripped.startswith(("$", "{", "<", "b")) and len(stripped) >= 8:
                        # Doesn't even start with any of the patterns — it's plain text.
                        fallback_mode = False
                        yield ("text", text_buffer)
                        text_buffer = ""
                    elif len(text_buffer) >= 120:
                        # Long enough to decide on the JSON-like patterns.
                        fallback_mode = _looks_like_tool_text(stripped)
                        if not fallback_mode:
                            yield ("text", text_buffer)
                            text_buffer = ""
    # End of stream: handle leftover buffer.
    if pending_calls:
        yield ("tool_calls", [pending_calls[i] for i in sorted(pending_calls)])
    elif fallback_mode is True and text_buffer:
        synth = _parse_text_fallback_tool_calls(text_buffer)
        if synth:
            yield ("tool_calls", [
                {"id": c.id, "name": c.function.name, "args": c.function.arguments}
                for c in synth
            ])
        else:
            # Couldn't parse — flush as text so the user still sees something.
            yield ("text", text_buffer)
    elif text_buffer:
        yield ("text", text_buffer)
