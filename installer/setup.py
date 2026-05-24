#!/usr/bin/env python3
"""Jade one-command installer (Windows / macOS / Linux).

Normally invoked by install.sh / install.ps1, but also runs directly:

    python installer/setup.py [flags]

It is idempotent — every step detects what's already present and skips it.
Runs on a bare system python (stdlib only); the heavy work happens inside the
project venv it creates.

Flags (mostly for debugging / partial runs):
    --model TAG               LLM to pull           (default: qwen2.5:7b-instruct)
    --venv PATH               venv to use/create    (default: detect or .venv)
    --skip-deps               don't create venv / install python deps
    --skip-ollama             don't install Ollama or pull the model
    --skip-autostart          don't configure login autostart
    --autostart-interactive   autostart with window+tray (default: voice-only)
    --no-smoke                skip the post-install smoke test
    --smoke-only              only run the smoke test against an existing venv
"""
import argparse
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "qwen2.5:7b-instruct"
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
OLLAMA_VERSION_URL = "http://localhost:11434/api/version"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def log(step, msg): print(f"[{step}] {msg}", flush=True)
def ok(msg): print(f"  ✓ {msg}", flush=True)
def warn(msg): print(f"  ! {msg}", flush=True)


def run(cmd, **kw):
    print(f"  $ {' '.join(map(str, cmd))}", flush=True)
    return subprocess.run(cmd, **kw)


def venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if IS_WIN else "bin")


def venv_python(venv: Path) -> Path:
    return venv_bin(venv) / ("python.exe" if IS_WIN else "python")


def venv_jade(venv: Path) -> Path:
    return venv_bin(venv) / ("jade.exe" if IS_WIN else "jade")


def detect_venv(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    for name in (".venv", ".venv312"):
        if (ROOT / name).exists():
            return ROOT / name
    return ROOT / ".venv"


def _ollama_up(timeout=2) -> bool:
    try:
        urllib.request.urlopen(OLLAMA_VERSION_URL, timeout=timeout)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# steps
# --------------------------------------------------------------------------- #
def ensure_uv() -> str:
    exe = shutil.which("uv")
    if exe:
        ok(f"uv present ({exe})")
        return exe
    log("uv", "installing uv from astral.sh ...")
    if IS_WIN:
        run(["powershell", "-NoProfile", "-Command",
             "irm https://astral.sh/uv/install.ps1 | iex"], check=True)
    else:
        run(["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"], check=True)
    for cand in (Path.home()/".local"/"bin"/"uv", Path.home()/".cargo"/"bin"/"uv"):
        if cand.exists():
            return str(cand)
    exe = shutil.which("uv")
    if not exe:
        raise SystemExit("uv installed but not on PATH — open a new shell and re-run.")
    return exe


def install_deps(uv: str, venv: Path):
    if not venv.exists():
        log("deps", f"creating venv at {venv}")
        run([uv, "venv", str(venv)], check=True)
    log("deps", "installing requirements + the `jade` command (this may take a few minutes)")
    run([uv, "pip", "install", "--python", str(venv_python(venv)),
         "-r", str(ROOT / "requirements.txt"), "-e", str(ROOT)], check=True)
    ok("dependencies installed")


def ensure_ollama(model: str):
    if not shutil.which("ollama"):
        log("ollama", "installing Ollama ...")
        if IS_LINUX:
            run(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], check=True)
        elif IS_MAC and shutil.which("brew"):
            run(["brew", "install", "ollama"], check=True)
        elif IS_WIN and shutil.which("winget"):
            run(["winget", "install", "--id", "Ollama.Ollama", "-e", "--silent",
                 "--accept-package-agreements", "--accept-source-agreements"], check=False)
        else:
            warn("Couldn't auto-install Ollama. Get it from https://ollama.com/download, then re-run.")
            return
    else:
        ok("Ollama present")

    if not _ollama_up():
        log("ollama", "starting `ollama serve` in the background ...")
        try:
            kw = {"creationflags": 0x08} if IS_WIN else {
                "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            subprocess.Popen(["ollama", "serve"], **kw)
        except Exception as e:
            warn(f"couldn't start ollama serve: {e}")
        for _ in range(20):
            if _ollama_up():
                break
            time.sleep(1)
    ok("Ollama server reachable" if _ollama_up() else "Ollama server not reachable (pull may fail)")
    _pull_if_missing(model)


def _pull_if_missing(model: str):
    """Pull an Ollama model unless it's already present."""
    try:
        listed = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10).stdout
        if model in listed:
            ok(f"model {model} already pulled")
            return
    except Exception:
        pass
    log("ollama", f"pulling {model} (large download, be patient) ...")
    run(["ollama", "pull", model], check=False)


def write_env(model: str):
    env = ROOT / ".env"
    if env.exists():
        ok(f".env exists at {env} (left as-is)")
        return
    env.write_text(
        "# Jade configuration. Edit values and restart Jade.\n"
        "# Real environment variables override anything set here.\n"
        f"OLLAMA_MODEL={model}\n"
        "# OLLAMA_BASE_URL=http://localhost:11434/v1\n"
        "# WHISPER_CPU=1   # keep Whisper on CPU, freeing VRAM for the LLM\n"
        "WHISPER_CPU=1\n"
        "# KOKORO_VOICE=af_bella:0.4,bf_emma:0.35,am_michael:0.25\n"
        "# JADE_VOICE_PITCH=1.0\n"
        "# Speaker recognition (run `jade --enroll` first). Lower = more lenient\n"
        "# about matching your voice; raise it if others get treated as you.\n"
        "# JADE_SPEAKER_THRESHOLD=0.45\n"
        "# JADE_SPEAKER_DEVICE=cpu\n"
        "# Barge-in: talk over Jade to interrupt her. Best with headphones; if her\n"
        "# own voice keeps interrupting her, raise JADE_BARGE_RMS or set =0.\n"
        "# JADE_BARGE_IN=1\n"
        "# JADE_BARGE_RMS=1500\n"
        "# Proactivity cadence + quiet hours (24h, wraps midnight) + post-speech cooldown.\n"
        "# JADE_PROACTIVE_INTERVAL=900\n"
        "# JADE_QUIET_START=23\n"
        "# JADE_QUIET_END=8\n"
        "# JADE_PROACTIVE_COOLDOWN=30\n"
        "# Vision model (run installer with --with-vision, or `ollama pull qwen2.5vl:3b`).\n"
        "# JADE_VISION_MODEL=qwen2.5vl:3b\n"
    )
    ok(f"wrote {env}")


def setup_autostart(venv: Path, interactive: bool):
    sys.path.insert(0, str(ROOT))
    import autostart
    cmd = [str(venv_jade(venv))] + (["--interactive"] if interactive else [])
    log("autostart", autostart.install(interactive=interactive, command=cmd))


def smoke_test(venv: Path) -> bool:
    smoke = ROOT / "installer" / "smoketest.py"
    return subprocess.run([str(venv_python(venv)), str(smoke)]).returncode == 0


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Install Jade.")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--venv")
    ap.add_argument("--skip-deps", action="store_true")
    ap.add_argument("--skip-ollama", action="store_true")
    ap.add_argument("--skip-autostart", action="store_true")
    ap.add_argument("--autostart-interactive", action="store_true")
    ap.add_argument("--with-vision", action="store_true",
                    help="Also pull a vision model so Jade can see the screen.")
    ap.add_argument("--vision-model", default="qwen2.5vl:3b")
    ap.add_argument("--no-smoke", action="store_true")
    ap.add_argument("--smoke-only", action="store_true")
    args = ap.parse_args()

    venv = detect_venv(args.venv)

    if args.smoke_only:
        raise SystemExit(0 if smoke_test(venv) else 1)

    print(f"== Jade installer ==  platform={sys.platform}  project={ROOT}  venv={venv}\n")

    if args.skip_deps:
        ok("skipping deps")
    else:
        install_deps(ensure_uv(), venv)

    write_env(args.model)

    if args.skip_ollama:
        ok("skipping Ollama")
    else:
        ensure_ollama(args.model)
        if args.with_vision:
            _pull_if_missing(args.vision_model)

    if args.skip_autostart:
        ok("skipping autostart")
    else:
        setup_autostart(venv, args.autostart_interactive)

    passed = True if args.no_smoke else smoke_test(venv)

    print("\n== Done ==")
    print(f"  Run now:  {venv_jade(venv)}")
    print(f"  Autostart at login was configured (toggle with `jade --uninstall-autostart`).")
    if not passed:
        print("  NOTE: smoke test reported a failure — see above.")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
