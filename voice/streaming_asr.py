"""Streaming ASR via faster-whisper, gated by webrtcvad.

Generator API: `for text in stream_recognition(): ...` yields lowercased
end-of-utterance transcriptions. Model loads lazily on first call so importing
this module is cheap.

While shared_state.SPEAKING is set (TTS playing), incoming mic frames are
dropped to prevent the Companion from transcribing its own voice.
"""
import envconfig  # noqa: F401  — load .env before reading WHISPER_* below
import collections
import ctypes
import os

# Pin OpenMP to a single backend BEFORE numpy/ctranslate2 import.
# Without this, ctranslate2's OpenMP collides with OpenBLAS's on the second
# transcribe call and segfaults.
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


def _preload_nvidia_libs():
    """Dlopen CUDA libs from `nvidia-*` pip wheels with RTLD_GLOBAL so ctranslate2
    finds them at runtime. Without this, libcublas.so.12 in the venv is invisible
    to ctranslate2's native backend (it doesn't look inside Python site-packages),
    and you'd have to export LD_LIBRARY_PATH manually before every launch.

    Failures here are silently ignored — if the libs aren't installed we'll just
    fall back to CPU. Loads in deterministic order: cublas before cudnn.
    """
    for pkg_name in ("nvidia.cublas.lib", "nvidia.cudnn.lib"):
        try:
            mod = __import__(pkg_name, fromlist=["*"])
        except ImportError:
            continue
        # The nvidia-* wheels are PEP 420 namespace packages: no __file__, use __path__.
        lib_dirs = []
        if getattr(mod, "__file__", None):
            lib_dirs.append(os.path.dirname(mod.__file__))
        if hasattr(mod, "__path__"):
            lib_dirs.extend(list(mod.__path__))
        for lib_dir in lib_dirs:
            try:
                fnames = sorted(os.listdir(lib_dir))
            except OSError:
                continue
            for fname in fnames:
                if fname.startswith("lib") and ".so" in fname:
                    try:
                        ctypes.CDLL(os.path.join(lib_dir, fname), mode=ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass


_preload_nvidia_libs()

import numpy as np

from shared_state import SPEAKING, STOP_EVENT


# large-v3-turbo: multilingual, ~5-6× faster than large-v3 on GPU with
# comparable accuracy on common languages. Right pick when you need to handle
# non-English words / accents / slang and still want low latency.
# WHISPER_MODEL env var overrides (e.g. "large-v3" for max accuracy at higher
# latency, or "medium" for a smaller multilingual model).
_MODEL_NAME = os.environ.get("WHISPER_MODEL", "large-v3-turbo")
SAMPLE_RATE = 16000
VAD_FRAME_MS = 30
VAD_FRAME_SAMPLES = SAMPLE_RATE * VAD_FRAME_MS // 1000   # 480
VAD_FRAME_BYTES = VAD_FRAME_SAMPLES * 2                  # 16-bit mono

# Trailing silence that ends a speech segment. 700ms keeps natural phrasing
# pauses ("stop... listening", "wait... actually...") inside the same segment,
# at the cost of ~200ms more latency before reply. The trade-off favors not
# losing words.
HANGOVER_MS = 700
HANGOVER_FRAMES = HANGOVER_MS // VAD_FRAME_MS

# Minimum continuous speech to actually start a segment. Filters out coughs,
# clicks, single-syllable noise.
MIN_SPEECH_MS = 180
MIN_SPEECH_FRAMES = MIN_SPEECH_MS // VAD_FRAME_MS

# Pre-roll: keep this many frames before voice trigger so we don't clip the
# start of the first word.
PREROLL_FRAMES = 10  # 300ms

# Hard ceiling on a single utterance. If we ever blow past this (e.g. broken VAD,
# clipped audio that looks like 100% voice), force-end the segment instead of
# growing the buffer unbounded.
MAX_SEGMENT_MS = 12000
MAX_SEGMENT_FRAMES = MAX_SEGMENT_MS // VAD_FRAME_MS

_model = None


def _ensure_model():
    """Lazy-load the Whisper model.

    Defaults to CUDA float16 (system cuBLAS + cuDNN required). Set WHISPER_CPU=1
    to force CPU int8 instead.
    """
    global _model
    if _model is not None:
        return _model
    from faster_whisper import WhisperModel

    if os.environ.get("WHISPER_CPU") != "1":
        # int8_float16 keeps activations in float16 but stores weights as int8 —
        # ~half the VRAM of pure float16 with near-identical accuracy. Lets large-v3-turbo
        # co-exist with Ollama's qwen2.5:7b on an 8GB GPU.
        compute = os.environ.get("WHISPER_COMPUTE_TYPE", "int8_float16")
        try:
            _model = WhisperModel(_MODEL_NAME, device="cuda", compute_type=compute)
            print(f"[whisper] {_MODEL_NAME} on CUDA ({compute})")
            return _model
        except Exception as e:
            print(f"[whisper] CUDA load failed ({type(e).__name__}: {e}); falling back to CPU int8")
    _model = WhisperModel(
        _MODEL_NAME,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        num_workers=1,
    )
    print(f"[whisper] {_MODEL_NAME} on CPU (int8, threads=4)")
    return _model


# Language: by default auto-detect (the user mixes English / Italian / Spanish).
# Whisper's auto-detect mis-fires on short or noisy utterances — we backstop
# that by ignoring detections under a confidence floor and falling back to the
# last-stable language. Set WHISPER_LANGUAGE=en (or "it"/"es"/etc.) to pin.
_WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "auto").strip().lower() or None
if _WHISPER_LANGUAGE in {"auto", "none", ""}:
    _WHISPER_LANGUAGE = None

# Set of allowed auto-detected languages. Whisper can pick Arabic/Russian on
# noisy English audio — clamp to languages the user actually speaks.
_ALLOWED_LANGS = {
    s.strip().lower()
    for s in os.environ.get("WHISPER_ALLOWED_LANGS", "en,it,es").split(",")
    if s.strip()
}
_LANG_CONFIDENCE_FLOOR = float(os.environ.get("WHISPER_LANG_CONFIDENCE", "0.6"))

_INITIAL_PROMPT = os.environ.get(
    "WHISPER_INITIAL_PROMPT",
    "We may be talking in English, Italian, or Spanish, sometimes mixing them.",
) or None

# Track the most recently confidently-detected language so we can backstop
# low-confidence single-word utterances ("yes", "ok") that auto-detect mangles.
_last_stable_lang = "en"


def _transcribe(speech_bytes: bytes) -> tuple[str, str]:
    """Transcribe a segment. Returns (text, detected_lang)."""
    global _last_stable_lang
    audio = np.frombuffer(speech_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    segments, info = _model.transcribe(
        audio,
        language=_WHISPER_LANGUAGE,
        initial_prompt=_INITIAL_PROMPT,
        beam_size=1,
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
    )
    text = " ".join(seg.text for seg in segments).strip()

    detected = (_WHISPER_LANGUAGE or info.language or "en").lower()
    conf = float(getattr(info, "language_probability", 1.0) or 1.0)
    if _WHISPER_LANGUAGE is None:
        # Reject low-confidence detections or unsupported languages — fall back
        # to the last stable language we saw.
        if detected not in _ALLOWED_LANGS or conf < _LANG_CONFIDENCE_FLOOR:
            detected = _last_stable_lang
        else:
            _last_stable_lang = detected
    return text, detected


def stream_recognition():
    import sounddevice as sd
    import webrtcvad

    _ensure_model()
    # webrtcvad: 0=least aggressive at filtering (calls almost everything speech),
    # 3=most aggressive (only confident speech). On a noisy mic 3 is the right call.
    vad = webrtcvad.Vad(3)

    print(f"[asr] default input device: {sd.query_devices(kind='input')['name']}")

    # Per-second mic / VAD heartbeat. Off by default; set ASR_DEBUG=1 to enable
    # when diagnosing mic gain or VAD issues.
    debug = os.environ.get("ASR_DEBUG") == "1"

    preroll = collections.deque(maxlen=PREROLL_FRAMES)
    speech_buffer = bytearray()
    consecutive_speech = 0
    consecutive_silence = 0
    triggered = False
    # Per-segment voiced-frame counter. Resets each utterance. Feeds the
    # tone classifier's voiced-ratio feature.
    seg_voiced_frames = 0
    seg_total_frames = 0
    _dbg_n = 0
    _dbg_peak = 0
    _dbg_voiced = 0

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=VAD_FRAME_SAMPLES,
        dtype="int16",
        channels=1,
    ) as stream:
        while not STOP_EVENT.is_set():
            data, _overflow = stream.read(VAD_FRAME_SAMPLES)
            frame = bytes(data)

            if SPEAKING.is_set():
                # Companion is talking. Reset state; whatever we hear is feedback.
                preroll.clear()
                speech_buffer.clear()
                consecutive_speech = 0
                consecutive_silence = 0
                triggered = False
                continue

            is_speech = vad.is_speech(frame, SAMPLE_RATE)

            if debug:
                _dbg_n += 1
                samples = np.frombuffer(frame, dtype=np.int16)
                p = int(np.max(np.abs(samples))) if samples.size else 0
                if p > _dbg_peak:
                    _dbg_peak = p
                if is_speech:
                    _dbg_voiced += 1
                if _dbg_n >= 33:  # ~1s at 30ms/frame
                    print(f"[asr-dbg] peak={_dbg_peak} voiced={_dbg_voiced}/{_dbg_n} triggered={triggered}")
                    _dbg_n = 0
                    _dbg_peak = 0
                    _dbg_voiced = 0

            if not triggered:
                preroll.append(frame)
                if is_speech:
                    consecutive_speech += 1
                    if consecutive_speech >= MIN_SPEECH_FRAMES:
                        triggered = True
                        speech_buffer.extend(b"".join(preroll))
                        consecutive_silence = 0
                else:
                    consecutive_speech = 0
                continue

            # Triggered: accumulate, watch for end-of-segment silence
            speech_buffer.extend(frame)
            seg_total_frames += 1
            if is_speech:
                consecutive_silence = 0
                seg_voiced_frames += 1
            else:
                consecutive_silence += 1

            segment_frames = len(speech_buffer) // VAD_FRAME_BYTES
            should_end = (
                consecutive_silence >= HANGOVER_FRAMES
                or segment_frames >= MAX_SEGMENT_FRAMES
            )
            if should_end:
                if segment_frames >= MAX_SEGMENT_FRAMES:
                    print(f"[asr] segment capped at {MAX_SEGMENT_MS}ms — check mic gain")
                segment_bytes = bytes(speech_buffer)
                text, detected_lang = _transcribe(segment_bytes)
                voiced_in_segment = seg_voiced_frames
                total_in_segment = seg_total_frames
                speech_buffer.clear()
                preroll.clear()
                consecutive_speech = 0
                consecutive_silence = 0
                seg_voiced_frames = 0
                seg_total_frames = 0
                triggered = False
                if text:
                    from voice.tone import features_from_segment
                    feats = features_from_segment(
                        segment_bytes,
                        text=text,
                        voiced_frames=voiced_in_segment,
                        total_frames=total_in_segment,
                        sample_rate=SAMPLE_RATE,
                    )
                    feats["detected_lang"] = detected_lang
                    yield text.lower(), feats
