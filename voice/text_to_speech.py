"""Sentence-streaming TTS — Kokoro primary, Piper fallback, espeak-ng floor.

Kokoro is an 82M-parameter neural TTS (Apache 2.0) that sounds genuinely
human on CPU. ~330MB one-time model download. Default voice 'af_heart' is
a warm female American; common alternates:
  KOKORO_VOICE=am_michael   (warm male)
  KOKORO_VOICE=af_nicole    (clear female)
  KOKORO_VOICE=af_bella     (fuller female)
  KOKORO_VOICE=bf_emma      (British, mature female)

One voice + English phonemizer is used for *everything* (see _speak_kokoro):
English words inside Italian/Spanish phrases then stay correctly pronounced.
JADE_VOICE_PITCH deepens the tone for a warmer / "mommy" voice (0.9 default;
lower = deeper). Set JADE_MULTILINGUAL_VOICE=1 to bring back per-language voices.

If Kokoro isn't installed or fails to load, we fall back to Piper (still
high quality, recognizable TTS). If Piper also fails, espeak-ng so the
voice loop never goes silent.

shared_state.SPEAKING set during playback so ASR drops mic frames and we
don't transcribe ourselves.
"""
import os
import re
import threading
import urllib.request
from pathlib import Path

from shared_state import SPEAKING


# Sentence-end matcher: punctuation followed by whitespace or end-of-stream.
# Used to split a streaming LLM reply into TTS-sized chunks so we can start
# speaking sentence 1 while the LLM is still generating sentence 2+.
_SENT_END = re.compile(r"[.!?]+[\"')\]]?(?=\s|$)")


# Deep-but-feminine blend: rich (Bella) + mature British (Emma) + a little male
# warmth (Michael) for depth, without going breathy/whispery. Override with the
# KOKORO_VOICE env var (a plain name or another blend spec).
KOKORO_DEFAULT_VOICE = "af_bella:0.4,bf_emma:0.35,am_michael:0.25"
PIPER_DEFAULT_VOICE = "en_US-amy-medium"

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
KOKORO_DIR = MODELS_DIR / "kokoro"
PIPER_DIR = MODELS_DIR / "piper"

KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
PIPER_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

_engine = None  # "kokoro", "piper", or "espeak"
_kokoro = None
_piper_voice = None
_pyttsx_engine = None
_init_lock = threading.Lock()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[tts] downloading {dest.name} (~{_remote_size_mb(url)}MB)...")
    urllib.request.urlretrieve(url, dest)


def _remote_size_mb(url: str) -> str:
    try:
        with urllib.request.urlopen(url) as r:
            n = int(r.headers.get("Content-Length", 0))
            return str(n // (1024 * 1024)) if n else "?"
    except Exception:
        return "?"


def _init_kokoro() -> bool:
    """Try to load Kokoro. Returns True on success."""
    global _kokoro
    try:
        from kokoro_onnx import Kokoro

        onnx_path = KOKORO_DIR / "kokoro-v1.0.onnx"
        voices_path = KOKORO_DIR / "voices-v1.0.bin"
        if not onnx_path.exists():
            _download(KOKORO_MODEL_URL, onnx_path)
        if not voices_path.exists():
            _download(KOKORO_VOICES_URL, voices_path)

        _kokoro = Kokoro(str(onnx_path), str(voices_path))
        voice = os.environ.get("KOKORO_VOICE", KOKORO_DEFAULT_VOICE)
        print(f"[kokoro] ready, voice={voice}")
        return True
    except Exception as e:
        print(f"[kokoro] init failed ({type(e).__name__}: {e}); trying piper")
        return False


def _piper_paths(voice_name: str):
    parts = voice_name.split("-")
    lang_region, name, quality = parts
    lang = lang_region.split("_")[0]
    onnx = PIPER_DIR / f"{voice_name}.onnx"
    cfg = PIPER_DIR / f"{voice_name}.onnx.json"
    if not onnx.exists() or not cfg.exists():
        base = f"{PIPER_HF_BASE}/{lang}/{lang_region}/{name}/{quality}/{voice_name}"
        print(f"[piper] downloading {voice_name} from huggingface...")
        PIPER_DIR.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(f"{base}.onnx", onnx)
        urllib.request.urlretrieve(f"{base}.onnx.json", cfg)
    return str(onnx), str(cfg)


def _init_piper() -> bool:
    global _piper_voice
    try:
        try:
            from piper import PiperVoice
        except ImportError:
            from piper.voice import PiperVoice

        voice_name = os.environ.get("PIPER_VOICE", PIPER_DEFAULT_VOICE)
        onnx, cfg = _piper_paths(voice_name)
        _piper_voice = PiperVoice.load(onnx, config_path=cfg)
        print(f"[piper] ready, voice={voice_name}")
        return True
    except Exception as e:
        print(f"[piper] init failed ({type(e).__name__}: {e}); falling back to espeak-ng")
        return False


def _init_espeak() -> None:
    global _pyttsx_engine
    if _pyttsx_engine is not None:
        return
    import pyttsx3
    _pyttsx_engine = pyttsx3.init()
    _pyttsx_engine.setProperty("rate", 175)


def _ensure_engine() -> str:
    global _engine
    with _init_lock:
        if _engine is not None:
            return _engine
        forced = os.environ.get("TTS_ENGINE", "").lower()
        if forced == "espeak":
            _init_espeak()
            _engine = "espeak"
        elif forced == "piper":
            _engine = "piper" if _init_piper() else ("espeak" if (_init_espeak() or True) else "espeak")
        elif forced == "kokoro":
            _engine = "kokoro" if _init_kokoro() else ("espeak" if (_init_espeak() or True) else "espeak")
        elif _init_kokoro():
            _engine = "kokoro"
        elif _init_piper():
            _engine = "piper"
        else:
            _init_espeak()
            _engine = "espeak"
        return _engine


def _resolve_tone_params(tone: str):
    """Pick speed + volume scaling for a given user tone. Falls back to the
    KOKORO_SPEED env var when no tone is supplied so manual tuning still works."""
    from voice.tone import TONE_SPEED, TONE_VOLUME
    if tone in TONE_SPEED:
        return TONE_SPEED[tone], TONE_VOLUME.get(tone, 1.0)
    try:
        return float(os.environ.get("KOKORO_SPEED", "1.15")), 1.0
    except ValueError:
        return 1.15, 1.0


# Language → (kokoro voice prefix, espeak/phonemizer locale code).
# Voices live in models/kokoro/voices-v1.0.bin (54 voices across 9 languages).
_LANG_VOICE = {
    "en": ("af_heart", "en-us"),   # default — keep af_heart
    "it": ("if_sara",  "it"),
    "es": ("ef_dora",  "es"),
    "fr": ("ff_siwis", "fr-fr"),
    "pt": ("pf_dora",  "pt"),
    "hi": ("hf_alpha", "hi"),
    "ja": ("jf_alpha", "ja"),
    "zh": ("zf_xiaobei", "zh"),
}


# Per-language voice switching is OFF by default: one consistent voice and
# English-based pronunciation, so English words embedded in Italian/Spanish
# phrases aren't mangled by a foreign phonemizer. Set JADE_MULTILINGUAL_VOICE=1
# to bring back the per-language voices in _LANG_VOICE above.
_MULTILINGUAL_VOICE = os.environ.get("JADE_MULTILINGUAL_VOICE") == "1"


def _voice_pitch() -> float:
    """Pitch multiplier for the voice. 1.0 = unchanged, <1.0 = deeper.

    Off by default (1.0): resampling the waveform down also drags the formants
    down, which is what makes a deepened female voice lose its femininity. Get
    depth from the *voice blend* instead (KOKORO_VOICE). This knob is here only
    as a last-resort fine-tune; expect some loss of feminine character below ~0.95.
    """
    try:
        return float(os.environ.get("JADE_VOICE_PITCH", "1.0"))
    except ValueError:
        return 1.0


# Cache of parsed blend specs -> numpy style vectors, so we resolve each spec once.
_voice_cache: dict = {}


def _resolve_voice_spec(spec: str):
    """Turn a KOKORO_VOICE spec into something Kokoro.create accepts.

    A plain name ('af_nicole') is returned as-is. A blend spec mixes voices by
    weight so the model renders one coherent timbre — formants stay intact, so
    you can get a deeper voice that's still audibly feminine:

        af_nicole:0.6,af_bella:0.4   (breathy + rich, equal-ish)
        af_nicole:0.75,am_michael:0.25  (breathy female + a touch of male depth)

    Weights are optional (default equal) and auto-normalized. Cached per spec.
    """
    spec = (spec or "").strip()
    if not spec or ("," not in spec and ":" not in spec):
        return spec or "af_heart"
    if spec in _voice_cache:
        return _voice_cache[spec]
    parts = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        name, _, w = item.partition(":")
        try:
            weight = float(w) if w else 1.0
        except ValueError:
            weight = 1.0
        parts.append((name.strip(), weight))
    if not parts:
        return "af_heart"
    total = sum(w for _, w in parts) or 1.0
    blend = None
    for name, w in parts:
        style = _kokoro.get_voice_style(name) * (w / total)
        blend = style if blend is None else blend + style
    _voice_cache[spec] = blend
    return blend


def _deepen(samples, pitch: float):
    """Lower pitch by `pitch` with no change to playback rate.

    We resample the waveform to more samples (stretch in time → lower
    frequencies); the caller generates the speech proportionally faster so the
    final clip keeps its pace. Clean FFT resample, no phase-vocoder artifacts.
    """
    if pitch == 1.0:
        return samples
    from scipy.signal import resample
    n = max(1, int(round(len(samples) / pitch)))
    return resample(samples, n).astype(samples.dtype)


def _speak_kokoro(text: str, tone: str = "neutral", lang: str = "en") -> None:
    """Stream Kokoro chunks to the speakers as they're synthesized.

    One consistent voice + English phonemizer for everything (so mixed-language
    phrases keep correct English pronunciation), optionally deepened in pitch.
    """
    import numpy as np
    import sounddevice as sd

    if _MULTILINGUAL_VOICE and lang in _LANG_VOICE and lang != "en":
        voice, kokoro_lang = _LANG_VOICE[lang]
    else:
        # One voice, English phonemizer for all languages. The spec may be a
        # plain name or a blend ("af_nicole:0.6,af_bella:0.4") — see _resolve_voice_spec.
        kokoro_lang = "en-us"
        spec = os.environ.get("KOKORO_VOICE")
        if not spec:
            try:
                from persona import load_config
                spec = load_config().get("voice") or KOKORO_DEFAULT_VOICE
            except Exception:
                spec = KOKORO_DEFAULT_VOICE
        voice = _resolve_voice_spec(spec)

    # Tone-driven voice swap is opt-in (TONE_VOICE_SWAP=1) — defaulting to
    # one voice keeps the Companion's identity consistent across turns.
    if os.environ.get("TONE_VOICE_SWAP") == "1":
        try:
            from voice.tone import TONE_VOICE
            voice = TONE_VOICE.get(tone, voice)
        except ImportError:
            pass

    speed, volume = _resolve_tone_params(tone)
    pitch = _voice_pitch()
    # Generate proportionally faster so deepening (which stretches the waveform)
    # restores the original duration.
    gen_speed = speed / pitch if pitch > 0 else speed

    def _emit(samples, sr):
        audio = _deepen(samples.astype(np.float32), pitch) * volume
        sd.play(audio, samplerate=sr)
        sd.wait()

    if hasattr(_kokoro, "create_stream"):
        import asyncio

        async def _run():
            async for samples, sr in _kokoro.create_stream(text, voice=voice, speed=gen_speed, lang=kokoro_lang):
                yield samples, sr

        loop = asyncio.new_event_loop()
        try:
            agen = _run()
            while True:
                try:
                    samples, sr = loop.run_until_complete(agen.__anext__())
                except StopAsyncIteration:
                    break
                _emit(samples, sr)
        finally:
            loop.close()
    else:
        samples, sr = _kokoro.create(text, voice=voice, speed=gen_speed, lang=kokoro_lang)
        _emit(samples, sr)


def _speak_piper(text: str) -> None:
    import numpy as np
    import sounddevice as sd

    sample_rate = _piper_voice.config.sample_rate
    if hasattr(_piper_voice, "synthesize"):
        stream = _piper_voice.synthesize(text)
    else:
        stream = _piper_voice.synthesize_stream_raw(text)
    for chunk in stream:
        if hasattr(chunk, "audio_int16_bytes"):
            audio_bytes = chunk.audio_int16_bytes
        elif isinstance(chunk, (bytes, bytearray)):
            audio_bytes = bytes(chunk)
        elif hasattr(chunk, "audio_int16_array"):
            audio_bytes = chunk.audio_int16_array.tobytes()
        else:
            continue
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        sd.play(audio, samplerate=sample_rate)
        sd.wait()


def _speak_espeak(text: str) -> None:
    _init_espeak()
    _pyttsx_engine.say(text)
    _pyttsx_engine.runAndWait()


def _speak_one(text: str, engine: str, tone: str = "neutral", lang: str = "en") -> None:
    """Synthesize one chunk on the active engine, with cascading fallbacks."""
    text = text.strip()
    if not text:
        return
    if engine == "kokoro":
        try:
            _speak_kokoro(text, tone=tone, lang=lang)
            return
        except Exception as e:
            print(f"[kokoro] runtime failure ({type(e).__name__}: {e}); piper for this chunk")
            if _piper_voice is None:
                _init_piper()
            if _piper_voice is not None:
                try:
                    _speak_piper(text)
                    return
                except Exception:
                    pass
            _speak_espeak(text)
            return
    if engine == "piper":
        try:
            _speak_piper(text)
            return
        except Exception as e:
            print(f"[piper] runtime failure ({type(e).__name__}: {e}); espeak for this chunk")
    _speak_espeak(text)


def speak(text: str, tone: str = "neutral", lang: str = "en") -> None:
    if not text or not text.strip():
        return
    engine = _ensure_engine()
    SPEAKING.set()
    try:
        _speak_one(text, engine, tone=tone, lang=lang)
    finally:
        SPEAKING.clear()


def speak_stream(token_iter, tone: str = "neutral", lang: str = "en") -> str:
    """Consume an iterator of token deltas. Speak each complete sentence as it
    arrives so the user hears the first sentence while the LLM is still working
    on the rest. `tone` modulates speed + playback volume; `lang` picks the
    voice + phonemizer locale. Returns the full text.
    """
    engine = _ensure_engine()
    SPEAKING.set()
    buf = ""
    full = []
    try:
        for token in token_iter:
            if not token:
                continue
            buf += token
            full.append(token)
            while True:
                m = _SENT_END.search(buf)
                if not m:
                    break
                end = m.end()
                sentence = buf[:end]
                buf = buf[end:].lstrip()
                if len(sentence.strip()) >= 4:
                    _speak_one(sentence, engine, tone=tone, lang=lang)
                elif buf:
                    buf = sentence + " " + buf
        if buf.strip():
            _speak_one(buf, engine, tone=tone, lang=lang)
    finally:
        SPEAKING.clear()
    return "".join(full)
