"""Shell runner with safety-tier classification.

`run_command(cmd)` classifies the command via tools.safety.classify_shell.
SAFE → runs immediately. CONFIRM → returns the pending sentinel for the agent
loop. DENY → refuses outright.
"""
import subprocess

from tools.filesystem import _Result
from tools.safety import classify_shell, bypass_enabled, SAFE, CONFIRM, DENY


DEFAULT_TIMEOUT = 30


def run_command(cmd: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    cmd = cmd.strip()
    if not cmd:
        return "Empty command"

    tier = classify_shell(cmd)
    if tier == DENY:
        return f"Refused: command is in the deny tier (system-destructive or catastrophic)"
    if tier == CONFIRM and not bypass_enabled():
        return _Result(CONFIRM, f"[PROPOSED, NOT YET EXECUTED] shell command: {cmd!r}",
                       "run_command", {"cmd": cmd})

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out ({timeout}s)"
    except Exception as e:
        return f"Error running command: {e}"

    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    parts = []
    if out:
        parts.append(out)
    if err:
        parts.append(f"[stderr]\n{err}")
    if result.returncode != 0 and not (out or err):
        parts.append(f"(exit code {result.returncode})")
    text = "\n".join(parts) or "(no output)"
    if len(text) > 5000:
        text = text[:5000] + "\n...(truncated)"
    return text
