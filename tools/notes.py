"""Personal notes + 'remember this document' — a small knowledge base on top of
the existing Chroma memory (memory.py).

take_note stores a quick spoken note; save_doc fetches a URL / PDF / text file
(reusing tools/summarize), summarizes it, and stores that; recall_notes searches
just these saved notes/docs. All three are registered **owner_only** — the
owner's knowledge base stays private from household members / guests.

Notes and docs land in the same Chroma collection as ordinary memories (tagged
kind="note"/"doc"), so they also surface in the general `recall` tool; these
tools just give the user an explicit, scoped way to add and query them.
"""
import memory


def take_note(text: str) -> str:
    """Save a quick note for later recall."""
    text = (text or "").strip()
    if not text:
        return "What would you like me to note?"
    memory.save_memory(text, kind="note")
    return "Noted."


def save_doc(source: str, label: str = "") -> str:
    """Read and summarize a URL, PDF, or text file, then save the summary so you
    can ask about it later. `source` is a URL or file path; `label` is an
    optional short name to file it under."""
    source = (source or "").strip()
    if not source:
        return "Give me a URL or file path to save."
    from tools.summarize import _extract
    text, err = _extract(source)
    if err:
        return err
    text = (text or "").strip()
    if not text:
        return "There was no readable text there to save."
    if len(text) > 12000:
        text = text[:12000]
    import llm
    try:
        summary = llm.chat([
            {"role": "system", "content": "You write a tight factual summary to be "
             "stored and recalled later. No markdown, no preamble — just the gist "
             "and the key facts in a few sentences."},
            {"role": "user", "content": text},
        ], temperature=0.3).strip()
    except Exception:
        summary = text[:1500]  # LLM down → keep a raw excerpt rather than nothing
    name = label.strip() or source
    memory.save_memory(f"[doc: {name}] {summary}", kind="doc")
    return f"Saved a summary of {name}. Ask me about it any time."


def recall_notes(query: str, k: int = 5) -> str:
    """Search your saved notes and documents for something."""
    if not (query or "").strip():
        return "What would you like me to look up in your notes?"
    hits = memory.get_memories(query, k=k, kinds=["note", "doc"])
    if not hits:
        return "I don't have any notes on that."
    return "\n".join(f"- {h}" for h in hits)
