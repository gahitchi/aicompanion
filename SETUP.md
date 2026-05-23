# Companion — Setup & Running

Local voice-first AI companion with a warm-friend persona and tone-adaptive responses. Runs against a local Ollama model. CLI, FastAPI dashboard, tkinter window, full voice loop (Whisper ASR + Kokoro TTS).

## Prerequisites

### Arch system packages

```bash
sudo pacman -S tk espeak-ng portaudio libayatana-appindicator alsa-utils cudnn
```

- `tk` — tkinter desktop window
- `espeak-ng` — pyttsx3 fallback TTS
- `portaudio` — sounddevice mic input
- `alsa-utils` — `aplay` (espeak's audio output)
- `cudnn` — required for Whisper on GPU
- `libayatana-appindicator` — system tray icon

### Ollama

```bash
# install: see https://ollama.com
ollama serve &
ollama pull qwen2.5:3b-instruct
```

Default LLM is `qwen2.5:3b-instruct` — fast on CPU/GPU and leaves VRAM for Whisper. Override via `OLLAMA_MODEL` env var. The OpenAI-compatible API at `http://localhost:11434/v1` is what `llm.py` talks to.

## One-time setup

```bash
cd ~/Desktop/aicompanion
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Python 3.12+ recommended. 3.14 works but some wheels (chromadb, webrtcvad) compile from source — first install takes a minute.

## Voice stack

The voice loop pulls models on first use — no manual downloads needed.

| Component | Model | Where | Auto-download |
|---|---|---|---|
| ASR | faster-whisper `large-v3-turbo` | `~/.cache/huggingface/` | yes (~1.6 GB) |
| TTS (primary) | Kokoro `af_heart` (default) | `models/kokoro/` | yes (~330 MB) |
| TTS (fallback) | Piper `en_US-amy-medium` | `models/piper/` | yes (~50 MB) |
| TTS (floor) | espeak-ng | system | already installed |

CUDA libs for Whisper live in the venv (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12==9.*`). `voice/streaming_asr.py:_preload_nvidia_libs()` dlopens them at import so ctranslate2 finds them without `LD_LIBRARY_PATH`.

## Environment variables

All optional. Most are tuning knobs.

| Var | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5:3b-instruct` | LLM tag. Override for 7b, uncensored, etc. |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint |
| `WHISPER_MODEL` | `large-v3-turbo` | Whisper model (alt: `distil-large-v3`, `medium`, `small`) |
| `WHISPER_CPU` | `0` | Set `1` to force Whisper on CPU when VRAM is tight |
| `WHISPER_COMPUTE_TYPE` | `int8_float16` | ctranslate2 quant on GPU |
| `KOKORO_VOICE` | `af_heart` | Kokoro speaker. Try `am_michael`, `bm_lewis`, `bf_emma` |
| `KOKORO_SPEED` | `1.15` | Baseline TTS speed (per-tone overrides below take precedence) |
| `PIPER_VOICE` | `en_US-amy-medium` | Piper fallback voice |
| `TTS_ENGINE` | unset | Force `kokoro` / `piper` / `espeak` |
| `TONE_RMS_LOW` | `350` | Tone classifier: below this RMS = quiet |
| `TONE_RMS_HIGH` | `2200` | Above this RMS = loud |
| `TONE_PITCH_LOW` | `130` | Hz; below this f0 = "low pitch" |
| `TONE_PITCH_HIGH` | `260` | Hz; above this f0 = "high pitch" |
| `TONE_PITCH_STD_HIGH` | `35` | Pitch variance threshold for excited / angry |
| `TONE_RATE_FAST` | `3.0` | Words/sec above which = fast |
| `TONE_RATE_SLOW` | `1.5` | Words/sec below which = slow |
| `TONE_SENT_NEG` / `TONE_SENT_POS` | `-0.35` / `+0.35` | VADER compound thresholds |
| `TONE_FLOOR` | `0.4` | Minimum confidence; below this → "neutral" |
| `ASR_TONE_LOG` | `0` | Set `1` to print full feature + per-tone score dump per turn |
| `TONE_VOICE_SWAP` | `0` | Set `1` to flip Kokoro voice based on tone (off by default — mid-conversation swaps are jarring) |
| `ASR_DEBUG` | `0` | Per-second mic + VAD peak/voiced heartbeat |

## Calibrating the tone classifier

```bash
python tone_demo.py
```

Speak in a few different registers. For each segment, the demo prints features (rms, pitch, rate, voiced ratio, sentiment, keyword hits) + per-tone scores + the picked tone. Read off your personal baselines, then set env vars to nudge the thresholds.

## Entry points

Activate the venv first (`source .venv/bin/activate`), then pick one:

| Command | What it runs |
|---|---|
| `python main.py` | CLI chat only. Type `agent: <task>` for ReAct agent mode. Type `quit` to exit. |
| `uvicorn server:app --host 127.0.0.1 --port 8000` | FastAPI dashboard only. `POST /chat`, `POST /task`, `GET /state`, `GET /memory`, `WebSocket /ws`. Static UI at `/`. |
| `python launcher.py` | Everything: tk window + FastAPI + autonomous loop + scheduler + voice + tray. Each interface degrades gracefully if its system dep is missing. |

## Known gotchas

- **Tray menu inert on KDE Plasma/Wayland.** The icon shows but click events don't propagate (pystray's GTK/AppIndicator backend vs. Plasma's StatusNotifier). Close the tk window via the X button to exit cleanly instead.
- **First model call is slow (30–90s).** Ollama warms `qwen2.5:7b-instruct` into RAM on first use. Subsequent calls are 2–6s.
- **Agent mode sometimes wastes turns** on irrelevant `recall` calls before reading the observation it already has. ReAct prompt could be tightened in `core/agent.py:run_task`.
- **Chroma WAL.** If killed mid-write, you may see SQLite WAL warnings on next start. Safe to ignore. To start clean, `rm -rf memory_db/` (loses vector memory; JSON state — emotion, identity, episodes — survives).

## State files (safe to delete to reset)

- `memory_db/` — Chroma vector store (semantic memory across sessions)
- `emotion.json` — mood / energy / curiosity scalars
- `identity_memory.json` — user profile + relationship state
- `episodes.json` — last conversation episodes
- `user.json` — user-model inferred attributes
- `episodes.json`, `goals.json`, `skills.json`, `policy.json`, `graph.json` — various per-module persistence

Everything is regenerated on first interaction.

## Code layout

- `core/agent.py` — the `Companion` class (`chat`, `run_task`)
- `llm.py` — single Ollama client
- `memory.py` — Chroma wrapper
- `persona.py` / `emotion.py` / `identity.py` / `episodic_memory.py` / `user_model.py` — personality + state tracking
- `tools/` — agent tools (read_file, write_file, run_command, search_web, recall, remember)
- `server.py` — unified FastAPI
- `launcher.py` — orchestrates all interfaces
- `ui/window.py` — tk window
- `voice/` — ASR (faster-whisper) + TTS (Kokoro / Piper / espeak) + wake-word + tone classifier (`voice/tone.py`) + conversation controller
- `tray.py` — system tray icon
- `autonomous_loop.py` — proactive in-character messages every 120s
- `scheduler.py` — time-based task firing
- `_legacy/` — files removed during consolidation, kept for review; safe to delete
- `_diag_agent.py` — verbose diagnostic for the ReAct loop; safe to delete
