"""Single memory API. Chroma persistent vector store at ./memory_db."""
import atexit
import uuid

import chromadb

client = chromadb.PersistentClient(path="./memory_db")
col = client.get_or_create_collection("memory")


def save_memory(text, kind="event"):
    """Store one piece of text. `kind` is metadata ('event', 'profile', 'reflection')."""
    if not text or not text.strip():
        return
    col.add(
        documents=[text.strip()],
        ids=[str(uuid.uuid4())],
        metadatas=[{"kind": kind}],
    )


def get_memories(query, k=5, kinds=None):
    """Return up to k texts most relevant to query. Empty list if none.

    `kinds` optionally restricts results by the `kind` metadata (e.g.
    ['note', 'doc']); None searches everything."""
    if not query or not query.strip():
        return []
    where = None
    if kinds:
        where = {"kind": kinds[0]} if len(kinds) == 1 else {"kind": {"$in": list(kinds)}}
    res = col.query(query_texts=[query], n_results=k, where=where)
    docs = res.get("documents") or []
    return docs[0] if docs else []


def add(text):
    save_memory(text, kind="event")


def search(query, k=5):
    mems = get_memories(query, k=k)
    return "\n".join(mems)


@atexit.register
def _flush():
    try:
        client._system.stop()
    except Exception:
        pass
