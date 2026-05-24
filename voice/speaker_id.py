"""Speaker recognition — decides whether the current utterance is the enrolled
owner's voice, so Jade can unlock personal memory only for them.

Engine: SpeechBrain ECAPA-TDNN (`speechbrain/spkrec-ecapa-voxceleb`) → 192-d
speaker embeddings, compared to an enrolled voiceprint by cosine similarity.

Design principles
-----------------
* **Fail-open.** No voiceprint enrolled, or the model can't load? ``identify()``
  returns ``owner=True`` so Jade behaves exactly as before. Voice gating is a
  convenience, never a lock you can get stuck behind (a cold or a noisy room
  must not lock you out of your own companion).
* **CPU by default.** Whisper and the LLM already want the GPU; ECAPA on a ~3s
  clip is well under 200ms on CPU. Override with ``JADE_SPEAKER_DEVICE=cuda``.
* **Local + private.** The voiceprint is a 192-float vector saved next to the
  other runtime state and gitignored. No raw audio is retained.

This is good personalization, **not** a hard security boundary: a recording of
your voice could pass, and the threshold trades off false-accepts vs. locking
you out. We deliberately bias toward not locking the owner out.
"""
import os
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "voiceprint.npz"
MODEL_DIR = ROOT / "models" / "spkrec-ecapa-voxceleb"
MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
SAMPLE_RATE = 16000

# Cosine similarity below this is never treated as the owner, even if a sloppy
# enrollment produced a looser adaptive threshold. ECAPA same/different speaker
# typically separates around here on clean speech.
_THRESHOLD_FLOOR = 0.25
_THRESHOLD_CEIL = 0.55

_model = None
_model_tried = False
_profile_cache = None
_profile_mtime = None
_warned = False


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
def _device() -> str:
    return os.environ.get("JADE_SPEAKER_DEVICE", "cpu").strip() or "cpu"


def _load_model():
    """Lazy-load ECAPA. Returns the classifier, or None if unavailable.

    Caches the failure too (``_model_tried``) so a missing/broken install costs
    one attempt, not one per utterance.
    """
    global _model, _model_tried, _warned
    if _model is not None:
        return _model
    if _model_tried:
        return None
    _model_tried = True
    try:
        try:
            from speechbrain.inference.speaker import EncoderClassifier
        except ImportError:  # speechbrain < 1.0 layout
            from speechbrain.pretrained import EncoderClassifier
        _model = EncoderClassifier.from_hparams(
            source=MODEL_SOURCE,
            savedir=str(MODEL_DIR),
            run_opts={"device": _device()},
        )
        return _model
    except Exception as e:  # noqa: BLE001 — any failure means "no speaker-id"
        if not _warned:
            print(f"[speaker] disabled (model unavailable: {type(e).__name__}: {e})")
            _warned = True
        return None


def warmup() -> None:
    """Pre-load the model in a background thread so the first real utterance
    doesn't pay the load cost. Only bothers if a voiceprint is enrolled."""
    if not is_enrolled():
        return
    threading.Thread(target=_load_model, name="speaker-warmup", daemon=True).start()


# --------------------------------------------------------------------------- #
# audio → embedding
# --------------------------------------------------------------------------- #
def pcm_to_float(segment_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """int16 PCM bytes → float32 mono in [-1, 1], resampled to 16 kHz if needed."""
    audio = np.frombuffer(segment_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if sample_rate != SAMPLE_RATE and audio.size:
        from scipy.signal import resample
        audio = resample(audio, int(round(audio.size * SAMPLE_RATE / sample_rate)))
    return audio.astype(np.float32)


def embed_float(wav: np.ndarray):
    """16 kHz mono float32 → L2-normalized 192-d speaker embedding, or None."""
    model = _load_model()
    if model is None or wav.size < SAMPLE_RATE // 2:  # need ~0.5s of audio
        return None
    import torch
    with torch.no_grad():
        e = model.encode_batch(torch.from_numpy(np.ascontiguousarray(wav)).float().unsqueeze(0))
    vec = e.squeeze().detach().cpu().numpy().astype(np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


def embed_pcm(segment_bytes: bytes, sample_rate: int = SAMPLE_RATE):
    return embed_float(pcm_to_float(segment_bytes, sample_rate))


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if not na or not nb:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# --------------------------------------------------------------------------- #
# profile (voiceprint) persistence
# --------------------------------------------------------------------------- #
def is_enrolled() -> bool:
    return PROFILE_PATH.exists()


def load_profile():
    """Return {centroid, threshold, count} or None. Cached by file mtime."""
    global _profile_cache, _profile_mtime
    if not PROFILE_PATH.exists():
        _profile_cache, _profile_mtime = None, None
        return None
    mtime = PROFILE_PATH.stat().st_mtime
    if _profile_cache is not None and mtime == _profile_mtime:
        return _profile_cache
    data = np.load(PROFILE_PATH, allow_pickle=False)
    _profile_cache = {
        "centroid": data["centroid"].astype(np.float32),
        "threshold": float(data["threshold"]),
        "count": int(data["count"]),
    }
    _profile_mtime = mtime
    return _profile_cache


def enroll_from_embeddings(embeddings: list) -> dict:
    """Average several owner embeddings into a voiceprint and persist it.

    The threshold is derived from how tightly the enrollment samples cluster:
    the looser the owner's own samples, the more lenient we must be to avoid
    rejecting them. Clamped to a sane band so a one-shot enrollment can't set
    something absurd.
    """
    embs = [e for e in embeddings if e is not None]
    if len(embs) < 2:
        raise ValueError("need at least 2 usable voice samples to enroll")
    mat = np.vstack(embs).astype(np.float32)
    centroid = mat.mean(axis=0)
    centroid /= np.linalg.norm(centroid) or 1.0

    # Self-consistency: each sample's similarity to the centroid.
    self_sims = np.array([_cosine(e, centroid) for e in embs])
    margin = float(os.environ.get("JADE_SPEAKER_MARGIN", "0.12"))
    thr = float(np.clip(self_sims.mean() - margin, _THRESHOLD_FLOOR, _THRESHOLD_CEIL))

    np.savez(
        PROFILE_PATH,
        centroid=centroid.astype(np.float32),
        threshold=np.float32(thr),
        count=np.int32(len(embs)),
    )
    global _profile_cache, _profile_mtime
    _profile_cache, _profile_mtime = None, None  # force reload
    return {
        "count": len(embs),
        "threshold": thr,
        "self_sim_mean": float(self_sims.mean()),
        "self_sim_min": float(self_sims.min()),
    }


def enroll(samples: list) -> dict:
    """Embed a list of 16 kHz float32 clips and save the voiceprint."""
    return enroll_from_embeddings([embed_float(s) for s in samples])


def reset() -> bool:
    """Delete the enrolled voiceprint. Returns True if one existed."""
    global _profile_cache, _profile_mtime
    _profile_cache, _profile_mtime = None, None
    if PROFILE_PATH.exists():
        PROFILE_PATH.unlink()
        return True
    return False


# --------------------------------------------------------------------------- #
# identification
# --------------------------------------------------------------------------- #
def _threshold(profile: dict) -> float:
    override = os.environ.get("JADE_SPEAKER_THRESHOLD")
    if override:
        try:
            return float(override)
        except ValueError:
            pass
    return profile["threshold"]


def identify(segment_bytes: bytes, sample_rate: int = SAMPLE_RATE):
    """Return ``(is_owner, score)`` for an utterance.

    Fail-open: if nothing is enrolled, the model is unavailable, or anything
    throws, returns ``(True, 1.0)`` so Jade keeps working as before.
    """
    profile = load_profile()
    if profile is None:
        return True, 1.0
    try:
        emb = embed_pcm(segment_bytes, sample_rate)
        if emb is None:
            return True, 1.0
        score = _cosine(emb, profile["centroid"])
        return score >= _threshold(profile), score
    except Exception as e:  # noqa: BLE001
        global _warned
        if not _warned:
            print(f"[speaker] identify failed, treating as owner: {type(e).__name__}: {e}")
            _warned = True
        return True, 1.0


# --------------------------------------------------------------------------- #
# enrollment recording (CLI helper)
# --------------------------------------------------------------------------- #
def record_samples(n: int = 5, seconds: float = 4.0) -> list:
    """Record ``n`` clips of ``seconds`` each from the default mic at 16 kHz mono.

    Returns a list of float32 numpy arrays. Used by ``jade --enroll``.
    """
    import sounddevice as sd
    import time

    print(f"\nLet's learn your voice. I'll record {n} short clips of ~{int(seconds)}s each.")
    print("Speak naturally — say anything (read a sentence, describe your day).\n")
    samples = []
    for i in range(n):
        input(f"  [{i + 1}/{n}] Press Enter, then start talking...")
        for c in (3, 2, 1):
            print(f"    recording in {c}...", end="\r", flush=True)
            time.sleep(1)
        print("    ● recording — speak now          ")
        buf = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                     channels=1, dtype="float32")
        sd.wait()
        clip = buf.reshape(-1)
        peak = float(np.max(np.abs(clip))) if clip.size else 0.0
        if peak < 0.01:
            print("    ! that clip was nearly silent — let's redo it.")
            continue
        samples.append(clip)
        print(f"    ✓ got it (peak {peak:.2f})\n")
    return samples
