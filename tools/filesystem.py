"""Filesystem operations scoped to $HOME + /tmp.

All paths go through tools.safety.classify_path to determine tier. Read ops on
in-scope paths run immediately; writes / deletes / out-of-scope reads return
the CONFIRM sentinel for the agent loop to handle.
"""
import os
import shutil
from pathlib import Path

from tools.safety import classify_path, bypass_enabled, SAFE, CONFIRM, DENY


def _needs_confirm(tier: str) -> bool:
    return tier == CONFIRM and not bypass_enabled()


def _resolve(path_str: str) -> Path:
    return Path(os.path.expanduser(path_str)).resolve()


class _Result:
    """Tools return either a string (SAFE result) or one of these sentinels."""
    def __init__(self, tier: str, description: str = "", tool: str = "", args: dict = None):
        self.tier = tier
        self.description = description
        self.tool = tool
        self.args = args or {}

    def __repr__(self):
        return f"_Result({self.tier}, {self.description!r})"


def read_file(path: str) -> str:
    tier = classify_path(path, "read")
    if tier == DENY:
        return f"Refused: cannot read {path} (system or denied path)"
    if _needs_confirm(tier):
        return _Result(CONFIRM, f"read file {path}", "read_file", {"path": path})
    p = _resolve(path)
    if not p.exists():
        return f"File not found: {p}"
    if p.is_dir():
        return f"{p} is a directory — use list_dir instead"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Read error: {e}"
    # Cap to keep LLM context from exploding
    if len(text) > 20000:
        return text[:20000] + f"\n...(truncated, file is {len(text)} chars)"
    return text


def write_file(path: str, content: str) -> str:
    tier = classify_path(path, "write")
    if tier == DENY:
        return f"Refused: cannot write to {path} (system or denied path)"
    if _needs_confirm(tier):
        preview = (content[:120] + "...") if len(content) > 120 else content
        return _Result(
            CONFIRM,
            f"[PROPOSED, NOT YET EXECUTED] write {len(content)} chars to {path}. "
            f"Preview: {preview!r}",
            "write_file",
            {"path": path, "content": content},
        )
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {p}"


def append_file(path: str, content: str) -> str:
    tier = classify_path(path, "append")
    if tier == DENY:
        return f"Refused: cannot append to {path}"
    if _needs_confirm(tier):
        return _Result(
            CONFIRM,
            f"append {len(content)} chars to {path}",
            "append_file",
            {"path": path, "content": content},
        )
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(content)
    return f"Appended to {p}"


def list_dir(path: str = "~") -> str:
    tier = classify_path(path, "read")
    if tier == DENY:
        return f"Refused: cannot list {path}"
    if _needs_confirm(tier):
        return _Result(CONFIRM, f"list directory {path}", "list_dir", {"path": path})
    p = _resolve(path)
    if not p.exists():
        return f"Not found: {p}"
    if not p.is_dir():
        return f"{p} is not a directory"
    try:
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return f"Permission denied: {p}"
    lines = []
    for e in entries[:200]:
        marker = "/" if e.is_dir() else ""
        try:
            size = "" if e.is_dir() else f"  ({e.stat().st_size} bytes)"
        except OSError:
            size = ""
        lines.append(f"  {e.name}{marker}{size}")
    if len(entries) > 200:
        lines.append(f"  ... ({len(entries) - 200} more)")
    return f"{p}:\n" + "\n".join(lines)


def mkdir(path: str) -> str:
    tier = classify_path(path, "mkdir")
    if tier == DENY:
        return f"Refused: cannot mkdir {path}"
    if _needs_confirm(tier):
        return _Result(CONFIRM, f"create directory {path}", "mkdir", {"path": path})
    p = _resolve(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"Created {p}"


def delete_file(path: str) -> str:
    tier = classify_path(path, "delete")
    if tier == DENY:
        return f"Refused: cannot delete {path}"
    p = _resolve(path)
    if not p.exists():
        return f"Already gone: {p}"
    if p.is_dir():
        return f"{p} is a directory — use delete_dir for that"
    if _needs_confirm(tier):
        return _Result(CONFIRM, f"[PROPOSED, NOT YET EXECUTED] DELETE file {p}", "delete_file", {"path": path})
    p.unlink()
    return f"Deleted {p}"


def delete_dir(path: str, recursive: bool = False) -> str:
    tier = classify_path(path, "delete")
    if tier == DENY:
        return f"Refused: cannot delete {path}"
    p = _resolve(path)
    if not p.exists():
        return f"Already gone: {p}"
    if not p.is_dir():
        return f"{p} is not a directory"
    if _needs_confirm(tier):
        descr = (f"[PROPOSED, NOT YET EXECUTED] RECURSIVELY DELETE directory {p}"
                 if recursive else f"[PROPOSED, NOT YET EXECUTED] DELETE empty directory {p}")
        return _Result(CONFIRM, descr, "delete_dir", {"path": path, "recursive": recursive})
    if recursive:
        shutil.rmtree(p)
    else:
        p.rmdir()
    return f"Deleted {p}"


def move(src: str, dst: str) -> str:
    src_tier = classify_path(src, "delete")
    dst_tier = classify_path(dst, "write")
    if DENY in (src_tier, dst_tier):
        return f"Refused: cannot move {src} → {dst}"
    sp = _resolve(src)
    dp = _resolve(dst)
    if not sp.exists():
        return f"Source not found: {sp}"
    if CONFIRM in (src_tier, dst_tier) and not bypass_enabled():
        return _Result(CONFIRM, f"[PROPOSED, NOT YET EXECUTED] move {sp} → {dp}", "move", {"src": src, "dst": dst})
    shutil.move(str(sp), str(dp))
    return f"Moved {sp} → {dp}"


def copy(src: str, dst: str) -> str:
    src_tier = classify_path(src, "read")
    dst_tier = classify_path(dst, "write")
    if DENY in (src_tier, dst_tier):
        return f"Refused: cannot copy {src} → {dst}"
    sp = _resolve(src)
    dp = _resolve(dst)
    if not sp.exists():
        return f"Source not found: {sp}"
    if CONFIRM in (src_tier, dst_tier) and not bypass_enabled():
        return _Result(CONFIRM, f"copy {sp} → {dp}", "copy", {"src": src, "dst": dst})
    if sp.is_dir():
        shutil.copytree(str(sp), str(dp))
    else:
        dp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(sp), str(dp))
    return f"Copied {sp} → {dp}"


def find_files(path: str, pattern: str) -> str:
    tier = classify_path(path, "read")
    if tier == DENY:
        return f"Refused: cannot search under {path}"
    if _needs_confirm(tier):
        return _Result(CONFIRM, f"search for '{pattern}' under {path}", "find_files",
                       {"path": path, "pattern": pattern})
    p = _resolve(path)
    if not p.is_dir():
        return f"{p} is not a directory"
    matches = []
    for hit in p.rglob(pattern):
        matches.append(str(hit))
        if len(matches) >= 100:
            matches.append(f"...(stopped at 100; refine the pattern)")
            break
    return "\n".join(matches) if matches else f"No matches for {pattern!r} under {p}"
