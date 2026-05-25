"""Summarize a URL, local text file, or PDF into a short spoken digest.

URLs reuse web.fetch_url; PDFs use pypdf; local files are read only within the
safe scope (tools.safety.classify_path), so a guest can't have her read arbitrary
owner files. The extracted text is summarized by the LLM in a plain spoken style.
SAFE — read only.
"""
import os
from pathlib import Path

from tools.safety import classify_path, SAFE


def _extract(source: str):
    """Return (text, error). Exactly one is non-None."""
    source = source.strip()
    if source.startswith("http://") or source.startswith("https://"):
        from tools.web import fetch_url
        return fetch_url(source), None
    p = Path(os.path.expanduser(source))
    if classify_path(str(p), "read") != SAFE:
        return None, f"I can only read files in your home or /tmp; {source} is outside that."
    if not p.exists():
        return None, f"File not found: {p}"
    if p.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            return "\n".join((pg.extract_text() or "") for pg in reader.pages), None
        except Exception as e:
            return None, f"Couldn't read that PDF: {type(e).__name__}: {e}"
    try:
        return p.read_text(encoding="utf-8", errors="replace"), None
    except Exception as e:
        return None, f"Couldn't read that file: {e}"


def summarize(source: str, question: str = "") -> str:
    """Summarize a URL / text file / PDF. Optional `question` focuses the summary."""
    text, err = _extract(source)
    if err:
        return err
    text = (text or "").strip()
    if not text:
        return "There was no readable text there to summarize."
    if len(text) > 12000:
        text = text[:12000]
    import llm
    ask = question.strip() or "Summarize this clearly in a few sentences."
    try:
        return llm.chat([
            {"role": "system", "content": "You summarize text concisely to be spoken "
             "aloud. No markdown, no preamble — just the summary."},
            {"role": "user", "content": f"{ask}\n\n---\n{text}"},
        ], temperature=0.3).strip()
    except Exception as e:
        return f"Summary error: {type(e).__name__}: {e}"
