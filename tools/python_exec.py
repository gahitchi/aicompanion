"""Run a snippet of Python in a subprocess. CONFIRM tier — could do anything."""
import subprocess
import sys

from tools.filesystem import _Result
from tools.safety import bypass_enabled, CONFIRM


def python_exec(code: str, timeout: int = 10) -> str:
    """Execute Python code in a fresh subprocess; return its stdout+stderr.

    Always CONFIRM tier — could read files, hit the network, etc.
    """
    if not bypass_enabled():
        preview = (code[:160] + "...") if len(code) > 160 else code
        return _Result(
            CONFIRM,
            f"execute Python code:\n  {preview}",
            "python_exec",
            {"code": code, "timeout": timeout},
        )
    return _run(code, timeout)


def _run(code: str, timeout: int = 10) -> str:
    """Actually run the code. Called by python_exec when bypass is active."""
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Code timed out ({timeout}s)"
    except Exception as e:
        return f"Execution error: {e}"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    parts = []
    if out:
        parts.append(out)
    if err:
        parts.append(f"[stderr]\n{err}")
    if r.returncode != 0 and not (out or err):
        parts.append(f"(exit {r.returncode})")
    text = "\n".join(parts) or "(no output)"
    return text[:5000] + ("\n...(truncated)" if len(text) > 5000 else "")
