# Jade

A local, voice-first AI companion with a warm-friend personality. She listens,
talks back in a natural voice, remembers your conversations, adapts to your
tone, acts on the real world (email, calendar, weather, music, and more), and
keeps you company — all running **on your machine** against a local Ollama
model. No cloud.

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

- **Voice loop** — faster-whisper ASR + Kokoro TTS, VAD-gated, tone-adaptive,
  with "Hey Jade" wake word and barge-in.
- **Memory** — Chroma vector store + episodic + an identity model that builds a
  picture of you over time.
- **Speaker recognition** — ECAPA voiceprints gate personal memory to your voice;
  recognized household members are greeted by name (fail-open, fully local).
- **Real-world tools** — email, Google Calendar, weather, news, timers, lists,
  reminders, web search, document/PDF summarizing, unit/currency conversion,
  commute ETAs, Spotify, a contacts book, and a daily spoken briefing.
- **Companion features** — voice games, roleplay, a mood journal with weekly
  reflections, voice memos & meeting transcription, spaced-repetition flashcards,
  expense tracking, and on-demand jokes / facts / debate.
- **Vision** — "look at my screen" / image Q&A via a local multimodal model.
- **Tools framework** — ~80 tools with SAFE/CONFIRM/DENY safety tiers and
  owner-gating, so guests never touch the owner's private tools.
- **Web dashboard** — a reactive sphere at `localhost:8000` you can also type to,
  with live mood/status and at-a-glance feature cards.
- **Multilingual** — replies in the language you speak (English / Italian /
  Spanish by default).

## Docs

Full setup, configuration, per-OS notes, and troubleshooting:
[**SETUP.md**](SETUP.md).

---

*Personal project — a companion named Jade.*
