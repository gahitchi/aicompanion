"""Speaker recognition — identifies who is speaking so Jade can unlock the
owner's personal memory only for them, and greet known household members by name.

Engine: SpeechBrain ECAPA-TDNN (`speechbrain/spkrec-ecapa-voxceleb`) → 192-d
speaker embeddings, compared to enrolled voiceprints by cosine similarity.

Profiles live in `speaker_profiles.npz`: one or more named voiceprints, exactly
one flagged as the owner. (A pre-existing single-owner `voiceprint.npz` is
migrated automatically.)

Design principles
-----------------
* **Fail-open.** No profiles enrolled, or the model can't load? ``identify()``
  returns owner=True so Jade behaves exactly as before — voice gating is a
  convenience, never a lock you can get stuck behind.
* **CPU by default.** Whisper and the LLM already want the GPU; ECAPA on a ~3s
  clip is well under 200ms on CPU. Override with ``JADE_SPEAKER_DEVICE=cuda``.
* **Local + private.** Voiceprints are 192-float vectors saved next to the other
  runtime state and gitignored. No raw audio is retained.

This is good personalization, **not** a hard security boundary: a recording of
a voice could pass, and the threshold trades false-accepts vs. lockout. We bias
toward not locking the owner out.
"""
import os
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PROFILES_PATH = ROOT / "speaker_profiles.npz"
LEGACY_PATH = ROOT / "voiceprint.npz"   # single-owner format, auto-migrated
MODEL_DIR = ROOT / "models" / "spkrec-ecapa-voxceleb"
MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
SAMPLE_RATE = 16000

# Cosine similarity below this is never treated as a match, even if a sloppy
# enrollment produced a looser adaptive threshold. ECAPA same/different speaker
# typically separates around here on clean speech.
_THRESHOLD_FLOOR = 0.25
_THRESHOLD_CEIL = 0.55

_model = None
_model_tried = False
_profiles_cache = None
_profiles_mtime = None
_warned = False


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
def _device() -> str:
    return os.environ.get("JADE_SPEAKER_DEVICE", "cpu").strip() or "cpu"


def _load_model():
    """Lazy-load ECAPA. Returns the classifier, or None if unavailable."""
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
    """Pre-load the model in a background thread. No-op unless someone enrolled."""
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
# profile store (named voiceprints)
# --------------------------------------------------------------------------- #
def _migrate_legacy():
    """Turn a pre-existing single-owner voiceprint.npz into an owner profile."""
    try:
        d = np.load(LEGACY_PATH, allow_pickle=False)
        return [{
            "name": "owner",
            "centroid": d["centroid"].astype(np.float32),
            "threshold": float(d["threshold"]),
            "owner": True,
            "count": int(d["count"]),
        }]
    except Exception:
        return []


def _load_profiles():
    """Return a list of profile dicts (cached by file mtime). May be empty."""
    global _profiles_cache, _profiles_mtime
    if PROFILES_PATH.exists():
        mtime = PROFILES_PATH.stat().st_mtime
        if _profiles_cache is not None and mtime == _profiles_mtime:
            return _profiles_cache
        data = np.load(PROFILES_PATH, allow_pickle=False)
        names = [str(n) for n in data["names"]]
        profiles = [{
            "name": names[i],
            "centroid": data["centroids"][i].astype(np.float32),
            "threshold": float(data["thresholds"][i]),
            "owner": bool(data["owners"][i]),
            "count": int(data["counts"][i]),
        } for i in range(len(names))]
        _profiles_cache, _profiles_mtime = profiles, mtime
        return profiles
    # No profiles file — migrate a legacy single voiceprint if present.
    if LEGACY_PATH.exists():
        migrated = _migrate_legacy()
        if migrated:
            _save_profiles(migrated)
            return migrated
    _profiles_cache, _profiles_mtime = None, None
    return []


def _save_profiles(profiles) -> None:
    global _profiles_cache, _profiles_mtime
    np.savez(
        PROFILES_PATH,
        names=np.array([p["name"] for p in profiles], dtype="U64"),
        centroids=np.vstack([p["centroid"] for p in profiles]).astype(np.float32),
        thresholds=np.array([p["threshold"] for p in profiles], dtype=np.float32),
        owners=np.array([p["owner"] for p in profiles], dtype=bool),
        counts=np.array([p.get("count", 0) for p in profiles], dtype=np.int32),
    )
    _profiles_cache, _profiles_mtime = None, None  # force reload


def is_enrolled() -> bool:
    return bool(_load_profiles())


def owner_name():
    for p in _load_profiles():
        if p["owner"]:
            return p["name"]
    return None


def list_profiles() -> list:
    return [{"name": p["name"], "owner": p["owner"], "count": p["count"],
             "threshold": p["threshold"]} for p in _load_profiles()]


def enroll_from_embeddings(embeddings: list, name: str = "owner",
                           is_owner: bool = True) -> dict:
    """Average several embeddings into a named voiceprint and persist it.

    Replacing a name updates that profile. Enrolling a new owner clears the
    owner flag on any previous owner.
    """
    embs = [e for e in embeddings if e is not None]
    if len(embs) < 2:
        raise ValueError("need at least 2 usable voice samples to enroll")
    mat = np.vstack(embs).astype(np.float32)
    centroid = mat.mean(axis=0)
    centroid /= np.linalg.norm(centroid) or 1.0

    self_sims = np.array([_cosine(e, centroid) for e in embs])
    margin = float(os.environ.get("JADE_SPEAKER_MARGIN", "0.12"))
    thr = float(np.clip(self_sims.mean() - margin, _THRESHOLD_FLOOR, _THRESHOLD_CEIL))

    profiles = [p for p in _load_profiles() if p["name"] != name]
    # First-ever enrollment is the owner regardless of the flag.
    if not any(p["owner"] for p in profiles):
        is_owner = True
    if is_owner:
        for p in profiles:
            p["owner"] = False
    profiles.append({
        "name": name, "centroid": centroid.astype(np.float32),
        "threshold": thr, "owner": bool(is_owner), "count": len(embs),
    })
    _save_profiles(profiles)
    return {
        "name": name, "owner": bool(is_owner), "count": len(embs),
        "threshold": thr, "self_sim_mean": float(self_sims.mean()),
        "self_sim_min": float(self_sims.min()),
    }


def enroll(samples: list, name: str = "owner", is_owner: bool = True) -> dict:
    """Embed a list of 16 kHz float32 clips and save a named voiceprint."""
    return enroll_from_embeddings([embed_float(s) for s in samples], name, is_owner)


def reset() -> bool:
    """Delete ALL enrolled profiles (and any legacy voiceprint). True if any existed."""
    global _profiles_cache, _profiles_mtime
    _profiles_cache, _profiles_mtime = None, None
    removed = False
    for path in (PROFILES_PATH, LEGACY_PATH):
        if path.exists():
            path.unlink()
            removed = True
    return removed


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
    """Return ``(is_owner, name, score)`` for an utterance.

    - nothing enrolled / model down / error → ``(True, None, 1.0)`` (fail-open)
    - best profile above its threshold        → ``(profile.owner, name, score)``
    - profiles exist but none match           → ``(False, None, best_score)`` (guest)
    """
    profiles = _load_profiles()
    if not profiles:
        return True, None, 1.0
    try:
        emb = embed_pcm(segment_bytes, sample_rate)
        if emb is None:
            return True, None, 1.0
        best, best_score = None, -1.0
        for p in profiles:
            s = _cosine(emb, p["centroid"])
            if s > best_score:
                best, best_score = p, s
        if best is not None and best_score >= _threshold(best):
            return bool(best["owner"]), best["name"], best_score
        return False, None, best_score
    except Exception as e:  # noqa: BLE001
        global _warned
        if not _warned:
            print(f"[speaker] identify failed, treating as owner: {type(e).__name__}: {e}")
            _warned = True
        return True, None, 1.0


# --------------------------------------------------------------------------- #
# enrollment recording (CLI helper)
# --------------------------------------------------------------------------- #
def record_samples(n: int = 5, seconds: float = 4.0) -> list:
    """Record ``n`` clips of ``seconds`` each from the default mic at 16 kHz mono.

    Returns a list of float32 numpy arrays. Used by ``jade --enroll``.
    """
    import sounddevice as sd
    import time

    print(f"\nLet's learn this voice. I'll record {n} short clips of ~{int(seconds)}s each.")
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
