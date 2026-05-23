"""Safety tier classifiers for shell commands and filesystem paths.

Three tiers:
  SAFE     — auto-run; no confirmation needed
  CONFIRM  — needs user yes/no before executing
  DENY     — refused outright (catastrophic or system-destructive)

Used by tools/runner.py and tools/filesystem.py to decide what gets through.
The Companion's `pending_action` state machine (core/agent.py) handles the
actual confirmation conversation with the user.

Defaults are intentionally conservative: unknown shell verbs → CONFIRM, paths
outside $HOME / /tmp → CONFIRM at minimum. False-positive CONFIRM is annoying
but recoverable; false-positive SAFE is dangerous.
"""
import contextlib
import os
import shlex
import threading
from pathlib import Path


SAFE = "safe"
CONFIRM = "confirm"
DENY = "deny"

# Thread-local bypass flag. When True, tools whose tier is CONFIRM should
# execute directly instead of returning the pending sentinel. Set by the
# registry's run() function when the user has already confirmed an action.
_state = threading.local()


def bypass_enabled() -> bool:
    return getattr(_state, "bypass", False)


@contextlib.contextmanager
def bypass():
    _state.bypass = True
    try:
        yield
    finally:
        _state.bypass = False


HOME = Path(os.path.expanduser("~")).resolve()
TMP = Path("/tmp").resolve()

# Shell verbs that are read-only / informational. SAFE by default.
_READ_ONLY_VERBS = {
    "ls", "cat", "pwd", "echo", "date", "uname", "head", "tail", "wc",
    "grep", "find", "stat", "file", "which", "whereis", "type", "id", "whoami",
    "hostname", "df", "du", "free", "ps", "top", "htop", "uptime", "history",
    "env", "printenv", "lsblk", "lscpu", "lspci", "lsusb", "lsmod", "uname",
    "ip", "ifconfig", "ss", "netstat", "ping", "host", "dig", "nslookup",
    "tree", "fc-list", "locale", "tldr",
    "diff", "cmp", "md5sum", "sha256sum", "basename", "dirname", "realpath",
    "sort", "uniq", "cut", "awk", "sed", "tr", "tee", "xargs",
    "jq", "yq", "curl", "wget",
}

# Verbs that MODIFY filesystem / system state. CONFIRM tier — never auto.
_MUTATING_VERBS = {
    "mv", "cp", "mkdir", "rm", "rmdir", "touch", "ln", "chmod", "chown",
    "ddrescue", "rsync", "tar", "zip", "unzip", "gunzip", "gzip",
    "pip", "uv", "npm", "yarn", "pnpm", "cargo", "go", "make", "cmake",
    "git", "ssh", "scp", "sftp",
    "python", "python3", "node", "ruby", "perl", "bash", "sh", "zsh",
    "xdg-open", "playerctl", "notify-send", "spectacle", "grim",
    "systemctl",  # user units only — CONFIRM, will check args
    "kill", "killall", "pkill",
    "crontab", "at",
}

# Catastrophic verbs / patterns — never run, even with confirmation.
_DENY_VERBS = {
    "sudo", "su", "doas", "pkexec", "runuser",
    "mkfs", "fdisk", "parted", "wipefs", "shred",
    "dd",   # any dd is high risk; could deny entirely or allow under CONFIRM,
            # but the safest default is full deny — user can run dd themselves.
    "reboot", "shutdown", "halt", "poweroff", "init",
    "swapoff", "swapon", "mount", "umount",
    "iptables", "nft", "firewall-cmd", "ufw",
    "useradd", "userdel", "usermod", "groupadd", "groupdel",
    "passwd", "chpasswd",
    "modprobe", "rmmod", "insmod",
    "sysctl",
}

# Sensitive path patterns — confirm even for read at SAFE tier paths.
_SENSITIVE_PATH_FRAGMENTS = (
    "/.ssh/", "/.gnupg/", "/.aws/", "/.config/keepassxc/", "/.password-store/",
    "/secrets/", "/.netrc", "/.pgpass",
)

# Sensitive filename patterns (suffixes / contains)
_SENSITIVE_NAME_PATTERNS = ("token", "secret", "credentials", "password")
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def _in_scope(path: Path) -> bool:
    """True if path is under $HOME or /tmp."""
    try:
        return path == HOME or path == TMP or HOME in path.parents or TMP in path.parents
    except (ValueError, OSError):
        return False


def _looks_sensitive(path: Path) -> bool:
    s = str(path)
    if any(frag in s for frag in _SENSITIVE_PATH_FRAGMENTS):
        return True
    name_lower = path.name.lower()
    if any(name_lower.endswith(sfx) for sfx in _SENSITIVE_SUFFIXES):
        return True
    if any(pat in name_lower for pat in _SENSITIVE_NAME_PATTERNS):
        return True
    return False


def classify_path(path_str: str, op: str) -> str:
    """Classify a filesystem operation. `op` is 'read', 'write', or 'delete'."""
    try:
        path = Path(os.path.expanduser(path_str)).resolve()
    except (ValueError, OSError):
        return DENY

    # Outright deny operations targeting critical system roots
    critical = {"/", "/boot", "/etc", "/usr", "/var", "/proc", "/sys", "/dev"}
    p_str = str(path)
    for c in critical:
        if op != "read" and (p_str == c or p_str.startswith(c + "/")):
            return DENY

    in_scope = _in_scope(path)

    if op == "read":
        # Most reads are SAFE in scope; sensitive paths CONFIRM even in scope.
        if not in_scope:
            return CONFIRM
        if _looks_sensitive(path):
            return CONFIRM
        return SAFE

    if op in ("write", "append", "mkdir", "create"):
        if not in_scope:
            return CONFIRM
        if _looks_sensitive(path):
            return CONFIRM
        return CONFIRM  # writes always confirm — even in scope. User can mark trusted later.

    if op in ("delete", "move", "overwrite"):
        return CONFIRM if in_scope else DENY

    # Unknown op — be safe
    return CONFIRM


def classify_shell(cmd: str) -> str:
    """Classify a shell command string by its leading verb + dangerous patterns."""
    cmd = cmd.strip()
    if not cmd:
        return DENY

    # Catch patterns that should be denied regardless of leading verb
    lower = cmd.lower()
    if "rm -rf /" in lower or "rm -fr /" in lower:
        return DENY
    if ">/dev/sd" in lower.replace(" ", "") or "> /dev/sd" in lower:
        return DENY
    if " :(){:|:&};:" in lower or ":(){:|:&};:" in lower.replace(" ", ""):
        return DENY  # fork bomb
    # Curl-pipe-to-shell is a famous footgun.
    if ("curl " in lower or "wget " in lower) and ("| sh" in lower or "| bash" in lower or "|sh" in lower or "|bash" in lower):
        return DENY

    try:
        parts = shlex.split(cmd, posix=True)
    except ValueError:
        # Malformed quoting — treat as CONFIRM, let the shell parse later.
        parts = cmd.split()
    if not parts:
        return DENY
    base = os.path.basename(parts[0])  # strip /usr/bin/ etc

    if base in _DENY_VERBS:
        return DENY
    if base in _READ_ONLY_VERBS:
        # Check for redirections to system paths even in read-only verbs.
        if any(arg.startswith(">/") or arg.startswith(">>/") for arg in parts[1:]):
            # Redirecting output of a "safe" command can write anywhere — CONFIRM.
            for arg in parts[1:]:
                if arg.startswith(">/") or arg.startswith(">>/"):
                    target = arg.lstrip(">").lstrip(">")
                    if classify_path(target, "write") == DENY:
                        return DENY
                    return CONFIRM
        return SAFE
    if base in _MUTATING_VERBS:
        return CONFIRM

    # Unknown verb — default to CONFIRM (user can always say yes).
    return CONFIRM


# Yes/no detection for the confirmation flow.
_YES_WORDS = {
    "yes", "yeah", "yep", "yup", "y", "ok", "okay", "sure", "fine",
    "go", "do it", "go ahead", "confirm", "confirmed", "please", "yes please",
    # Italian (user's secondary language per memory)
    "sì", "si", "certo", "vai", "fallo",
    # Spanish (mentioned in Whisper initial_prompt)
    "sí", "claro", "dale", "hazlo",
}

_NO_WORDS = {
    "no", "nope", "nah", "n", "cancel", "stop", "wait", "nevermind",
    "never mind", "don't", "do not", "abort",
    "no gracias", "no thanks",
    # Italian
    "no", "non", "fermo", "annulla", "ferma",
}


def is_yes(text: str) -> bool:
    s = text.strip().lower().strip(".,!?;: ")
    if s in _YES_WORDS:
        return True
    words = set(s.split())
    # Any yes-word appearing anywhere in the input counts.
    return bool(words & _YES_WORDS)


def is_no(text: str) -> bool:
    s = text.strip().lower().strip(".,!?;: ")
    if s in _NO_WORDS:
        return True
    words = set(s.split())
    return bool(words & _NO_WORDS)
