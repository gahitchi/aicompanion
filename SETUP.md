# Jade — Setup & Running

Local, voice-first AI companion with a warm-friend persona and tone-adaptive
responses. Everything runs on your machine against a local Ollama model — no
cloud. Interfaces: full voice loop (Whisper ASR + Kokoro TTS), a tkinter desktop
window, a FastAPI dashboard, and a CLI.

Runs on **Linux, macOS, and Windows**.

---

## Quick start (one command)

The installer sets up a virtualenv, installs Python deps + the `jade` command,
installs Ollama and pulls the model, and configures login autostart. It's
idempotent — safe to re-run.

**Linux / macOS**
```bash
curl -LsSf https://raw.githubusercontent.com/gahitchi/aicompanion/main/install.sh | bash
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/gahitchi/aicompanion/main/install.ps1 | iex
```

Already have the repo cloned? Run it locally instead:
```bash
bash install.sh                 # Linux/macOS
powershell -ExecutionPolicy Bypass -File install.ps1   # Windows
```

Then:
```bash
jade --enroll     # (optional) teach Jade your voice — see "Voice recognition"
jade              # start talking
```

Useful installer flags (pass straight through the bootstrap):
`--model qwen2.5:3b-instruct` (lighter LLM), `--skip-ollama`, `--skip-autostart`,
`--smoke-only`. Full list: `python installer/setup.py --help`.

---

## What you need

| | Minimum | Recommended |
|---|---|---|
| Python | 3.10 | 3.12 |
| RAM | 8 GB | 16 GB |
| GPU | none (CPU works) | NVIDIA 8 GB VRAM (Whisper + 7B LLM together) |
| Disk | ~3 GB for models | — |

- **Ollama** runs the LLM. The installer fetches it; or get it from
  <https://ollama.com/download>. Default model is `qwen2.5:7b-instruct`
  (drop to `qwen2.5:3b-instruct` on low-VRAM machines via `--model`).
- **No GPU?** Set `WHISPER_CPU=1` in `.env` (the installer does this by default)
  so Whisper runs on CPU and leaves room for the LLM.

### Per-OS system bits

Most native libraries ship inside the Python wheels (PortAudio via
`sounddevice`, the VAD via `webrtcvad-wheels`, espeak-ng via `espeakng-loader`),
so there's usually nothing to install by hand. Exceptions:

- **Linux** — install PortAudio + Tk from your package manager, plus the tray
  lib if you want the system-tray icon. On Arch:
  ```bash
  sudo pacman -S tk portaudio alsa-utils libayatana-appindicator
  # GPU Whisper additionally wants: cudnn
  ```
  (Debian/Ubuntu equivalents: `python3-tk libportaudio2 alsa-utils
  libayatana-appindicator3-1`.)
- **macOS** — nothing extra to install. You **must grant Microphone permission**
  the first time (see Per-OS notes).
- **Windows** — nothing extra; the wheels bundle everything.

---

## Manual setup (instead of the installer)

```bash
git clone https://github.com/gahitchi/aicompanion
cd aicompanion

# Create a venv (uv is fastest, but plain venv is fine)
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate

pip install -r requirements.txt -e .   # -e . installs the `jade` command

# LLM
ollama serve &                         # if not already running
ollama pull qwen2.5:7b-instruct
```

Config lives in a `.env` file at the repo root (the installer writes one; copy
the keys from the table below). `envconfig.py` loads it before anything reads
the environment, and real environment variables always win over `.env`.

---

## Running

`jade` is the cross-platform entry point (installed by `pip install -e .` or the
installer). Pick a mode:

| Command | What it runs |
|---|---|
| `jade` | Voice-only, headless. Best for autostart. |
| `jade --interactive` | Voice **+** desktop window **+** system tray. |
| `jade --no-welcome` | Skip the spoken startup greeting. |
| `python main.py` | CLI text chat only. Type `agent: <task>` for ReAct mode; `quit` to exit. |
| `uvicorn server:app --port 8000` | FastAPI dashboard only. `POST /chat`, `POST /task`, `GET /state`, `GET /memory`, `WebSocket /ws`; UI at `/`. |
| `python launcher.py` | The everything-launcher `jade` wraps (window + API + voice + scheduler + tray). |

Each interface degrades gracefully if its system dependency is missing (e.g. no
Tk → no window, but voice + API still run).

---

## Autostart at login

```bash
jade --install-autostart      # start automatically at login
jade --uninstall-autostart    # stop doing that
```

Where it installs (handled by `autostart.py`):

| OS | Mechanism |
|---|---|
| Linux | systemd **user** unit at `~/.config/systemd/user/jade.service` |
| macOS | LaunchAgent at `~/Library/LaunchAgents/com.jade.companion.plist` |
| Windows | a `Jade.cmd` shim in the Startup folder |

- **Linux**: to keep her running across logout / when you're not logged in,
  `loginctl enable-linger $USER`. Manage with the usual
  `systemctl --user {status,restart,disable} jade` and tail logs with
  `journalctl --user -u jade -f`. Tuning (model, `WHISPER_CPU`) goes in `.env`,
  not the unit file — so restart Jade after editing `.env`.
- An existing systemd unit is **left untouched** by `--install-autostart` so
  your hand-tuned settings survive; delete it first if you want a fresh one.

---

## Voice recognition (optional)

Jade can learn the owner's voice and load personal memories **only** when she
hears it. Unrecognized voices get a warm but impersonal Jade who won't reveal
or write anything about the owner.

```bash
jade --enroll           # record ~5 short clips, builds your voiceprint
jade --enroll-status    # show whether one is enrolled + the match threshold
jade --reset-voiceprint # delete it (every voice is treated as owner again)
```

- Engine: SpeechBrain ECAPA-TDNN (`speechbrain/spkrec-ecapa-voxceleb`), CPU by
  default so it doesn't compete with the LLM for VRAM. Model caches under
  `models/spkrec-ecapa-voxceleb/`.
- The voiceprint is a 192-float vector in `voiceprint.npz` (gitignored, no raw
  audio kept). It's personalization, **not** hard security — and it **fails
  open**: with no voiceprint enrolled (or `speechbrain` missing), Jade behaves
  exactly as before. Typed CLI/API input is always treated as the owner.
- Tune matching with `JADE_SPEAKER_THRESHOLD` in `.env` (lower = more lenient).
  If Jade keeps treating you as a guest, lower it or re-enroll somewhere quiet.
- Run `jade --enroll` in a normal terminal (it needs the mic), then restart
  Jade so the running service picks up the voiceprint.

---

## Per-OS notes

**macOS**
- First run, macOS prompts for **Microphone** access — grant it (or
  System Settings → Privacy & Security → Microphone → enable your terminal /
  Jade). Without it the mic stream is silent.
- For spoken notifications / app-control, you may also be asked for
  **Notifications** and **Accessibility** permissions.
- If Gatekeeper blocks a downloaded helper, allow it once in
  Privacy & Security.

**Windows**
- SmartScreen may warn on the `install.ps1` one-liner; it's the bootstrap in
  this repo. Review it first if you prefer.
- Microphone: Settings → Privacy & security → Microphone → allow desktop apps.
- Media-key control (play/pause/next) uses virtual key codes via the Windows
  API — no extra install.

**Linux**
- Tray menu can be inert on **KDE Plasma / Wayland** (pystray's
  GTK/AppIndicator backend vs. Plasma's StatusNotifier). The icon shows but
  clicks may not register — exit via the window's X button, or run headless.
- Pick a non-default mic by setting it as the system default input, or via
  `sounddevice`. Set `ASR_DEBUG=1` to print a mic level/VAD heartbeat.

---

## Voice stack

Models download on first use — no manual steps.

| Component | Model | Where | Auto-download |
|---|---|---|---|
| ASR | faster-whisper `large-v3-turbo` | `~/.cache/huggingface/` | yes (~1.6 GB) |
| TTS (primary) | Kokoro (blended voice, see `KOKORO_VOICE`) | `models/kokoro/` | yes (~330 MB) |
| TTS (fallback) | Piper `en_US-amy-medium` | `models/piper/` | yes (~50 MB) |
| TTS (floor) | espeak-ng (via `espeakng-loader`) | bundled wheel | already present |
| Speaker ID | SpeechBrain ECAPA-TDNN | `models/spkrec-ecapa-voxceleb/` | yes (~20 MB, on enroll) |

On NVIDIA GPUs, the CUDA libs for Whisper come from the venv
(`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`); `voice/streaming_asr.py`
`_preload_nvidia_libs()` dlopens them at import so ctranslate2 finds them
without `LD_LIBRARY_PATH`.

---

## Configuration (`.env`)

All optional — most are tuning knobs. Set them in `.env` at the repo root.

| Var | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct` | LLM tag. Use `qwen2.5:3b-instruct` for low VRAM. |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint |
| `WHISPER_MODEL` | `large-v3-turbo` | Whisper model (alt: `distil-large-v3`, `medium`, `small`) |
| `WHISPER_CPU` | `0` | `1` forces Whisper on CPU (frees VRAM for the LLM) |
| `WHISPER_COMPUTE_TYPE` | `int8_float16` | ctranslate2 quant on GPU |
| `WHISPER_LANGUAGE` | `auto` | Pin a language (`en`/`it`/`es`/…) or auto-detect |
| `WHISPER_ALLOWED_LANGS` | `en,it,es` | Languages auto-detect is allowed to pick |
| `KOKORO_VOICE` | `af_bella:0.4,bf_emma:0.35,am_michael:0.25` | Kokoro voice or blend (`name:weight,…`) |
| `KOKORO_SPEED` | `1.15` | Baseline TTS speed (per-tone overrides take precedence) |
| `JADE_VOICE_PITCH` | `1.0` | Optional DSP pitch (1.0 = off; blending is preferred) |
| `JADE_MULTILINGUAL_VOICE` | `0` | `1` phonemizes per detected language (default: English voice for all) |
| `PIPER_VOICE` | `en_US-amy-medium` | Piper fallback voice |
| `TTS_ENGINE` | unset | Force `kokoro` / `piper` / `espeak` |
| `JADE_SPEAKER_THRESHOLD` | enroll-calibrated | Voice-match cutoff (lower = more lenient) |
| `JADE_SPEAKER_DEVICE` | `cpu` | Device for the speaker model (`cpu`/`cuda`) |
| `ASR_DEBUG` | `0` | Per-second mic + VAD peak/voiced heartbeat |
| `ASR_TONE_LOG` | `0` | Full feature + per-tone score dump per turn |

Tone-classifier thresholds (`TONE_RMS_LOW/HIGH`, `TONE_PITCH_*`, `TONE_RATE_*`,
`TONE_SENT_*`, `TONE_FLOOR`, `TONE_VOICE_SWAP`) are also env-tunable — see
"Calibrating the tone classifier".

---

## Calibrating the tone classifier

```bash
python tone_demo.py
```

Speak in a few registers. For each segment the demo prints features (rms, pitch,
rate, voiced ratio, sentiment, keyword hits) + per-tone scores + the picked
tone. Read off your personal baselines, then set the `TONE_*` env vars to nudge
the thresholds.

---

## Troubleshooting

- **First model call is slow (30–90s).** Ollama warms the model into RAM on
  first use. Subsequent calls are 2–6s.
- **She transcribes herself / loops.** Mic is picking up her own TTS — use
  headphones, or lower speaker volume. `SPEAKING` already gates the mic while
  she talks.
- **TTS sounds robotic (espeak).** Kokoro failed to load and fell back to the
  espeak floor. Check the startup log — usually a phonemizer/espeak issue; the
  smoke test (`python installer/setup.py --smoke-only`) reports the live engine.
- **Speaker gating treats you as a guest.** Lower `JADE_SPEAKER_THRESHOLD`, or
  re-enroll somewhere quiet (`jade --enroll`).
- **Chroma WAL warnings** after a hard kill: safe to ignore. To start clean,
  delete `memory_db/` (loses vector memory; JSON state survives).
- **macOS mic silent**: grant Microphone permission (Per-OS notes).

---

## State files (safe to delete to reset)

- `memory_db/` — Chroma vector store (semantic memory across sessions)
- `emotion.json` — mood / energy / curiosity scalars
- `identity_memory.json` — user profile + relationship state
- `episodes.json` — recent conversation episodes
- `user.json` — user-model inferred attributes
- `voiceprint.npz` — enrolled owner voiceprint (delete to disable voice gating)
- `followups.json`, `consolidator_state.json`, `goals.json` — per-module persistence

Everything regenerates on first interaction. None of these are tracked by git.

---

## Code layout

- `jade_cli.py` — the cross-platform `jade` entry point (flags → launcher / enroll / autostart)
- `launcher.py` — orchestrates all interfaces (window + API + voice + scheduler + tray)
- `installer/` — `setup.py` (one-command installer) + `smoketest.py`
- `install.sh` / `install.ps1` — thin bootstrappers for the installer
- `autostart.py` — per-OS login autostart (systemd / launchd / Startup)
- `platform_io.py` — cross-platform OS integration (notify, screenshot, battery, open app/url)
- `envconfig.py` — loads `.env` before anything reads the environment
- `core/agent.py` — the `Companion` class (`chat`, `chat_stream`, `run_task`)
- `llm.py` — single Ollama client
- `memory.py` — Chroma wrapper; `persona.py` / `emotion.py` / `identity.py` / `episodic_memory.py` / `user_model.py` — personality + state
- `tools/` — agent tools (filesystem, system, apps, media, web, safety tiers)
- `voice/` — ASR (`streaming_asr.py`), TTS (`text_to_speech.py`), wake word, tone classifier (`tone.py`), speaker ID (`speaker_id.py`), conversation controller
- `server.py` — unified FastAPI; `ui/window.py` — tk window; `tray.py` — system tray
- `autonomous_loop.py` — proactive in-character messages; `scheduler.py` — time-based tasks
- `tests/test_cross_platform.py` — the CI import/autostart smoke test
