# Jade

A local, voice-first AI companion with a warm-friend personality. She listens,
talks back in a natural voice, remembers your conversations, adapts to your
tone, and can use tools (open apps, control media, search the web, read/write
files) — all running **on your machine** against a local Ollama model. No cloud.

Runs on **Linux, macOS, and Windows**.

## Install (one command)

**Linux / macOS**
```bash
curl -LsSf https://raw.githubusercontent.com/gahitchi/aicompanion/main/install.sh | bash
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/gahitchi/aicompanion/main/install.ps1 | iex
```

The installer creates a virtualenv, installs the `jade` command and its deps,
installs Ollama and pulls the model, and sets up login autostart. It's
idempotent and safe to re-run.

## Use

```bash
jade --enroll     # (optional) teach Jade your voice — she then unlocks your
                  #            personal memory only when she hears you
jade              # start talking (voice-only)
jade --interactive   # add the desktop window + tray
```

## What's inside

- **Voice loop** — faster-whisper ASR + Kokoro TTS, VAD-gated, tone-adaptive.
- **Memory** — Chroma vector store + episodic + an identity model that builds a
  picture of you over time.
- **Speaker recognition** — ECAPA voiceprints gate personal memory to your voice
  (fail-open, fully local; see SETUP).
- **Tools** — filesystem, media, apps, web, with SAFE/CONFIRM/DENY safety tiers.
- **Multilingual** — replies in the language you speak (English / Italian /
  Spanish by default).

## Docs

Full setup, configuration, per-OS notes, and troubleshooting:
[**SETUP.md**](SETUP.md).

---

*Personal project — a companion named Jade.*
