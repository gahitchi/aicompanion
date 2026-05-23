"""Load .env from the project root before anything reads os.environ.

Import this FIRST in every entry point and in modules that read environment
variables at import time (llm.py, voice/streaming_asr.py):

    import envconfig  # noqa: F401

`load_dotenv` is idempotent and uses override=False, so real environment
variables (e.g. systemd `Environment=`) still take precedence over the .env
file. If python-dotenv isn't installed we silently no-op and the app runs on
the real environment alone.

The .env path is resolved relative to this file, not the cwd, so it's found
even when Jade is launched headless by systemd / launchd / Task Scheduler.
"""
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _load() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=False)


_load()
