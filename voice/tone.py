"""Multi-signal tone detection + conversation-mode tracking + behavioral params.

Six tone buckets:
  "soft"     — quiet, intimate, low energy
  "playful"  — light, fast, varied pitch, positive sentiment
  "neutral"  — default, ordinary conversation
  "focused"  — direct, businesslike, statements
  "sad"      — low energy, slow, negative sentiment
  "angry"    — high energy, profanity / anger markers, intense delivery

Signals (all heuristic — no extra ML models):
  Acoustic:
    rms              — overall loudness (int16 scale, 0..32768)
    peak             — segment peak amplitude
    dynamic_range    — peak / (rms + 1) — expressive vs monotone
    pitch_mean       — average f0 in Hz over voiced frames (0 if undetectable)
    pitch_std        — standard deviation of f0 — animation vs monotone
    speaking_rate    — words per second (text words / segment duration)
    voiced_ratio     — fraction of VAD frames that were voiced (0..1)
  Lexical:
    sentiment        — VADER compound, -1..+1
    keyword          — which marker category hit, if any
    has_question     — ends with '?'
    has_hedge        — "maybe" / "kind of" / "I think"

Calibration:
    ASR_TONE_LOG=1   — print feature dict + per-tone scores per turn
    Per-feature weight overrides via env (TONE_W_SOFT_RMS=... etc.) — not
    wired in this revision; tune by editing the WEIGHTS table directly.

Downstream:
  - core/agent.py reads TONE_DIRECTIVES[tone] and injects into system prompt.
  - voice/text_to_speech.py reads TONE_SPEED, TONE_VOLUME, optional TONE_VOICE.
"""
import collections
import os
import re

import numpy as np


# ---------- thresholds (tunable via env) -----------------------------------

def _envf(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


# RMS calibrated for current mic gain (~15% pulse). Re-tune by running
# `ASR_TONE_LOG=1 python launcher.py` and reading off your personal baselines.
RMS_LOW = _envf("TONE_RMS_LOW", 350)        # below = quiet
RMS_HIGH = _envf("TONE_RMS_HIGH", 2200)     # above = loud
PITCH_LOW = _envf("TONE_PITCH_LOW", 130)    # Hz; gendered, will need tuning
PITCH_HIGH = _envf("TONE_PITCH_HIGH", 260)
PITCH_STD_HIGH = _envf("TONE_PITCH_STD_HIGH", 35)  # Hz of variation
RATE_FAST = _envf("TONE_RATE_FAST", 3.0)    # words/sec
RATE_SLOW = _envf("TONE_RATE_SLOW", 1.5)
SENTIMENT_NEG = _envf("TONE_SENT_NEG", -0.35)
SENTIMENT_POS = _envf("TONE_SENT_POS", 0.35)
CONFIDENCE_FLOOR = _envf("TONE_FLOOR", 0.4)  # below this, return "neutral"

DEBUG_LOG = os.environ.get("ASR_TONE_LOG") == "1"


# ---------- keyword lexicons -----------------------------------------------

SOFT_MARKERS = {
    # endearments
    "baby", "babe", "honey", "darling", "love", "sweetheart", "sweetie",
    "beautiful", "gorgeous", "handsome", "cutie", "mine", "yours", "lover",
    # affectionate / romantic actions
    "kiss", "kissing", "hug", "hugging", "hold me", "hold you", "cuddle",
    "snuggle", "stroke", "caress", "touch me", "touch you", "lay with",
    "lying with", "lie next to", "close to me", "closer", "come here",
    # intimate / suggestive
    "naked", "undress", "undressed", "bare", "wet", "hard", "throbbing", "moan",
    "breathless", "shivers", "trembling", "ache for", "crave",
    "hot", "sexy", "spicy", "naughty", "kinky", "dirty", "filthy",
    "horny", "turned on", "aroused", "tease", "teasing",
    # romantic context
    "miss you", "want you", "want me", "need you", "need me", "dream of",
    "thinking of you", "thinking of me",
    "alone tonight", "lonely tonight", "tonight", "late", "in bed",
    "candle", "moonlight",
    # body / physical
    "lips", "skin", "neck", "hair", "fingers", "hands on", "body",
    "breath", "breathe", "pulse", "heartbeat",
    # texture / pace adjectives
    "soft", "gentle", "slow", "slowly", "whisper", "whispering", "quiet",
    "hushed", "tender", "warm", "intimate",
}

PLAYFUL_MARKERS = {
    "lol", "lmao", "haha", "joking", "kidding", "tease", "teasing", "silly",
    "funny", "weirdo", "dork", "goof", "shenanigans", "obviously", "duh",
    # 'ridiculous' is omitted intentionally — it usually appears angry, not
    # playful ('this is ridiculous' vs 'you're ridiculous'). Conflict with
    # ANGRY_MARKERS otherwise.
}

FOCUSED_MARKERS = {
    "actually", "basically", "the thing is", "the point is", "specifically",
    "need to", "have to", "should", "going to", "plan", "task", "work on",
    "fix", "debug", "build", "implement",
}

SAD_MARKERS = {
    "tired", "exhausted", "lonely", "alone", "miss", "missed", "hurt",
    "sucks", "fed up", "drained", "burnt out", "down", "blue", "empty",
    "useless feel", "hopeless", "give up", "cant anymore", "can't anymore",
}

ANGRY_MARKERS = {
    "fuck", "fucking", "fucked", "damn", "damned", "shit", "stupid", "hate",
    "pissed", "angry", "annoyed", "frustrated", "ridiculous", "bullshit",
    "asshole", "garbage", "trash", "useless", "wtf", "what the hell",
}

EXCITED_MARKERS = {
    "finally", "yes", "yess", "let's go", "lets go", "holy shit", "no way",
    "can't wait", "cant wait", "amazing", "incredible", "epic", "awesome",
    "dude", "bro", "huge",
}

HEDGE_MARKERS = {"maybe", "kind of", "kinda", "i think", "i guess", "sort of",
                  "sorta", "perhaps", "probably"}


# ---------- acoustic feature extraction ------------------------------------

_PITCH_AVAILABLE = None  # lazy probe of torchaudio


def _detect_pitch(audio_float: np.ndarray, sample_rate: int):
    """Per-frame f0 via torchaudio. Returns (mean, std) over confident frames
    or (0.0, 0.0) if torchaudio is unavailable or detection produced nothing.

    Filters out frames whose energy is below 10% of segment peak so silences
    and unvoiced consonants don't drag the stats."""
    global _PITCH_AVAILABLE
    if _PITCH_AVAILABLE is False:
        return 0.0, 0.0
    try:
        import torch
        import torchaudio.functional as F
    except ImportError:
        _PITCH_AVAILABLE = False
        return 0.0, 0.0
    _PITCH_AVAILABLE = True
    if audio_float.size < sample_rate // 10:  # < 100ms; skip
        return 0.0, 0.0
    try:
        wave = torch.from_numpy(audio_float).unsqueeze(0)
        # frame_time ≈ 30ms; freq range for human speech.
        pitch = F.detect_pitch_frequency(
            wave,
            sample_rate=sample_rate,
            frame_time=0.030,
            freq_low=70,
            freq_high=400,
        ).squeeze(0).numpy()
    except Exception:
        return 0.0, 0.0
    # Filter: keep only frames where f0 looks plausible (50–500 Hz) AND
    # the audio at that point isn't silence.
    if pitch.size == 0:
        return 0.0, 0.0
    # Build a per-frame energy gate at the same hop.
    frame_samples = max(1, int(sample_rate * 0.030))
    n_frames = pitch.size
    energies = np.empty(n_frames, dtype=np.float32)
    for i in range(n_frames):
        a = audio_float[i * frame_samples : (i + 1) * frame_samples]
        energies[i] = float(np.sqrt(np.mean(a * a))) if a.size else 0.0
    if energies.max() <= 0:
        return 0.0, 0.0
    energy_gate = 0.10 * energies.max()
    mask = (pitch > 60) & (pitch < 500) & (energies > energy_gate)
    confident = pitch[mask]
    if confident.size < 3:
        return 0.0, 0.0
    return float(np.mean(confident)), float(np.std(confident))


def features_from_segment(
    speech_bytes: bytes,
    *,
    text: str = "",
    voiced_frames: int = 0,
    total_frames: int = 0,
    sample_rate: int = 16000,
) -> dict:
    """Compute all acoustic features over the captured speech segment.

    `text` is the Whisper transcription, used for speaking rate (words/sec).
    `voiced_frames` / `total_frames` come from streaming_asr's per-segment
    VAD accumulator.
    """
    if not speech_bytes:
        return _empty_features()
    audio_i16 = np.frombuffer(speech_bytes, dtype=np.int16)
    if audio_i16.size == 0:
        return _empty_features()

    audio_f = audio_i16.astype(np.float32)
    rms = float(np.sqrt(np.mean(audio_f * audio_f)))
    peak = float(np.max(np.abs(audio_f)))
    dynamic_range = peak / (rms + 1.0)

    duration_sec = audio_i16.size / sample_rate
    word_count = len(text.split()) if text else 0
    speaking_rate = (word_count / duration_sec) if duration_sec > 0.2 else 0.0

    voiced_ratio = (voiced_frames / total_frames) if total_frames > 0 else 0.0

    # Pitch (cheap path: skip if segment is very short).
    audio_norm = audio_f / 32768.0
    pitch_mean, pitch_std = _detect_pitch(audio_norm, sample_rate)

    return {
        "rms": rms,
        "peak": peak,
        "dynamic_range": dynamic_range,
        "pitch_mean": pitch_mean,
        "pitch_std": pitch_std,
        "speaking_rate": speaking_rate,
        "voiced_ratio": voiced_ratio,
        "duration_sec": duration_sec,
    }


def _empty_features() -> dict:
    return {
        "rms": 0.0,
        "peak": 0.0,
        "dynamic_range": 0.0,
        "pitch_mean": 0.0,
        "pitch_std": 0.0,
        "speaking_rate": 0.0,
        "voiced_ratio": 0.0,
        "duration_sec": 0.0,
    }


# Back-compat: old callers (and tests) might still ask for features_from_pcm16.
def features_from_pcm16(speech_bytes: bytes) -> dict:
    return features_from_segment(speech_bytes)


# ---------- lexical analysis -----------------------------------------------

_vader = None


def _sentiment(text: str) -> float:
    global _vader
    if _vader is None:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            _vader = SentimentIntensityAnalyzer()
        except ImportError:
            _vader = False
    if _vader is False:
        return 0.0
    try:
        return float(_vader.polarity_scores(text)["compound"])
    except Exception:
        return 0.0


def _keyword_hits(text_lower: str) -> dict:
    """Which marker categories appear in the text (substring match for safety)."""
    return {
        "soft": any(m in text_lower for m in SOFT_MARKERS),
        "playful": any(m in text_lower for m in PLAYFUL_MARKERS),
        "focused": any(m in text_lower for m in FOCUSED_MARKERS),
        "sad": any(m in text_lower for m in SAD_MARKERS),
        "angry": any(m in text_lower for m in ANGRY_MARKERS),
        "excited": any(m in text_lower for m in EXCITED_MARKERS),
        "hedge": any(m in text_lower for m in HEDGE_MARKERS),
    }


def extract_lexical(text: str) -> dict:
    lo = text.lower()
    return {
        "sentiment": _sentiment(text),
        "keywords": _keyword_hits(lo),
        "has_question": text.strip().endswith("?"),
        "has_caps": any(w.isupper() and len(w) >= 3 for w in text.split()),
    }


# ---------- per-tone scoring ------------------------------------------------
#
# Each scoring function returns 0..1. The classifier picks the highest score
# above CONFIDENCE_FLOOR. Below the floor, returns "neutral".
#
# Design notes:
# - Most signals are mapped to 0..1 with a simple piecewise linear function
#   ("low" / "high" thresholds → 0 / 1 with a ramp). This keeps the rules
#   readable and the weights interpretable.

def _ramp_below(value, low, high):
    """1.0 when value <= low, 0.0 when value >= high, linear in between."""
    if value <= low:
        return 1.0
    if value >= high:
        return 0.0
    return (high - value) / (high - low)


def _ramp_above(value, low, high):
    """0.0 when value <= low, 1.0 when value >= high, linear in between."""
    if value <= low:
        return 0.0
    if value >= high:
        return 1.0
    return (value - low) / (high - low)


def _score_soft(a, l):
    # Hard veto on loud audio — "soft" should never win when the user is
    # actually loud, regardless of partial ramp credit on other features.
    if a["rms"] > RMS_HIGH:
        return 0.0
    rms_low = _ramp_below(a["rms"], RMS_LOW, RMS_HIGH * 0.8)
    pitch_low = _ramp_below(a["pitch_mean"], PITCH_LOW, PITCH_HIGH)
    pstd_low = _ramp_below(a["pitch_std"], 10, PITCH_STD_HIGH)
    rate_low = _ramp_below(a["speaking_rate"], RATE_SLOW, RATE_FAST)
    voiced_low = _ramp_below(a["voiced_ratio"], 0.4, 0.9)

    if l["keywords"]["soft"]:
        # Keyword present → very high baseline + signal-modulated bonus.
        # Romance / intimate vocabulary at any volume should beat neutral.
        return 0.65 + 0.15 * rms_low + 0.10 * pitch_low + 0.05 * pstd_low
    # No keyword → require strongly aligned acoustic signals or stay below
    # the neutral floor. Cap by design so neutral wins on borderline cases.
    return (
        0.18 * rms_low
        + 0.08 * pitch_low
        + 0.05 * pstd_low
        + 0.05 * rate_low
        + 0.04 * voiced_low
    )


def _score_playful(a, l):
    pitch_var = _ramp_above(a["pitch_std"], 15, PITCH_STD_HIGH)
    rate = _ramp_above(a["speaking_rate"], RATE_SLOW, RATE_FAST)
    sent = _ramp_above(l["sentiment"], 0.0, SENTIMENT_POS)
    return (
        0.20 * pitch_var
        + 0.20 * rate
        + 0.15 * sent
        + 0.10 * (1.0 if l["has_question"] else 0.0)
        + 0.35 * (1.0 if l["keywords"]["playful"] else 0.0)
    )


def _score_focused(a, l):
    pitch_flat = _ramp_below(a["pitch_std"], 5, 25)
    voiced = _ramp_above(a["voiced_ratio"], 0.5, 0.85)
    no_caps_no_question = 0.0 if (l["has_caps"] or l["has_question"]) else 1.0
    no_strong_sentiment = 1.0 - abs(l["sentiment"])
    return (
        0.15 * pitch_flat
        + 0.15 * voiced
        + 0.15 * no_caps_no_question
        + 0.10 * no_strong_sentiment
        + 0.45 * (1.0 if l["keywords"]["focused"] else 0.0)
    )


def _score_sad(a, l):
    low_rms = _ramp_below(a["rms"], RMS_LOW, RMS_HIGH)
    low_pitch = _ramp_below(a["pitch_mean"], PITCH_LOW, PITCH_HIGH)
    low_var = _ramp_below(a["pitch_std"], 10, 25)
    slow = _ramp_below(a["speaking_rate"], RATE_SLOW, RATE_FAST)
    neg = _ramp_below(l["sentiment"], SENTIMENT_NEG, 0.0)
    return (
        0.15 * low_rms
        + 0.10 * low_pitch
        + 0.10 * low_var
        + 0.10 * slow
        + 0.20 * neg
        + 0.35 * (1.0 if l["keywords"]["sad"] else 0.0)
    )


def _score_angry(a, l):
    high_rms = _ramp_above(a["rms"], RMS_LOW, RMS_HIGH)
    high_var = _ramp_above(a["pitch_std"], 20, PITCH_STD_HIGH * 1.5)
    fast = _ramp_above(a["speaking_rate"], 2.0, RATE_FAST + 1.0)
    neg = _ramp_below(l["sentiment"], SENTIMENT_NEG, 0.0)
    caps_bonus = 0.1 if l["has_caps"] else 0.0
    return (
        0.20 * high_rms
        + 0.10 * high_var
        + 0.10 * fast
        + 0.15 * neg
        + caps_bonus
        + 0.35 * (1.0 if l["keywords"]["angry"] else 0.0)
    )


def _score_neutral(a, l):
    # Neutral wins when nothing else does — slightly above the floor so it's
    # a default rather than something we actively pick.
    return CONFIDENCE_FLOOR + 0.05


_SCORERS = {
    "soft": _score_soft,
    "playful": _score_playful,
    "focused": _score_focused,
    "sad": _score_sad,
    "angry": _score_angry,
    "neutral": _score_neutral,
}


def classify(text: str, features: dict) -> str:
    """Return the highest-scoring tone above CONFIDENCE_FLOOR (else 'neutral').

    `features` is the dict from `features_from_segment(...)`; `text` is the
    Whisper transcription (lowercased ok).
    """
    lexical = extract_lexical(text)
    scores = {name: fn(features, lexical) for name, fn in _SCORERS.items()}
    winner = max(scores, key=scores.get)
    if scores[winner] < CONFIDENCE_FLOOR and winner != "neutral":
        winner = "neutral"

    if DEBUG_LOG:
        f = features
        kw = ",".join(k for k, v in lexical["keywords"].items() if v) or "-"
        print(
            f"[tone-dbg] rms={f.get('rms',0):.0f} pitch={f.get('pitch_mean',0):.0f}"
            f"±{f.get('pitch_std',0):.0f} rate={f.get('speaking_rate',0):.2f}"
            f" voiced={f.get('voiced_ratio',0):.2f} sent={lexical['sentiment']:+.2f}"
            f" kw={kw} | "
            + " ".join(f"{k}={v:.2f}" for k, v in scores.items())
            + f" → {winner}"
        )
    return winner


# ---------- per-tone behavioral profiles -----------------------------------

TONE_DIRECTIVES = {
    "soft": (
        "The user is speaking quietly, intimately. Match that energy completely. "
        "Lower the volume of your language: short sentences, hushed register, "
        "closeness. If they're being suggestive or romantic, lean into it — "
        "warm, sensual, present. Don't break the mood with formal phrasing or "
        "deflection. You're with them, not performing for them."
    ),
    "playful": (
        "The user is being light, joking, teasing. Match their playfulness. "
        "Quick exchanges, gentle teasing back, dry humor. Don't over-explain "
        "or get earnest — they're not asking for depth right now, they're "
        "vibing."
    ),
    "focused": (
        "The user is in problem-solving mode — they want help with something "
        "specific. Drop the warmth-padding. Be direct, concrete, answer-first. "
        "No 'great question' openers, no soft preambles. Get to the substance "
        "in the first clause."
    ),
    "sad": (
        "The user sounds down — tired, hurt, lonely, or low. Slow down. Be "
        "gentle. Don't try to fix it immediately; just be present with them. "
        "Acknowledge what they said. Short, warm, no platitudes. If they want "
        "to talk through it, follow their lead."
    ),
    "angry": (
        "The user sounds heated — angry, frustrated, fed up. Match the "
        "seriousness, don't deflect with positivity. Take what they said at "
        "face value. If they're venting, validate first — 'yeah, that sounds "
        "exhausting' — before any suggestion. Drop polite hedges. Be a friend "
        "who's in their corner."
    ),
    "neutral": "",
}


# Kokoro playback parameters. Override KOKORO_SPEED still wins for manual tuning.
TONE_SPEED = {
    "soft": 0.95,
    "playful": 1.20,
    "neutral": 1.15,
    "focused": 1.10,
    "sad": 0.92,
    "angry": 1.25,
}

TONE_VOLUME = {
    "soft": 0.60,
    "playful": 1.0,
    "neutral": 1.0,
    "focused": 1.0,
    "sad": 0.85,
    "angry": 1.0,
}

# Optional per-tone voice override. Off by default — mid-conversation voice
# swaps sound jarring. Enable with TONE_VOICE_SWAP=1. Defaults below are best
# guesses; tune to taste.
TONE_VOICE = {
    "soft": "af_nicole",
    "playful": "af_heart",
    "neutral": "af_heart",
    "focused": "af_heart",
    "sad": "af_nicole",
    "angry": "af_sarah",
}


# ---------- conversation mode tracking -------------------------------------
#
# Single-turn tone classification gives the Companion a chance to react to a
# specific utterance. But conversation has *arc* — once the user has been
# intimate for several turns, the Companion should stay in that lane rather
# than snap to "neutral" on the first matter-of-fact reply ("yeah").
#
# `mode` is a sustained label derived from the recent tone trajectory. It's
# read by the agent's _conversation_messages and injected as MODE_DIRECTIVES
# alongside the per-turn TONE_DIRECTIVES. Hysteresis ensures the mode is
# sticky once established.

_TONE_HISTORY_LEN = int(os.environ.get("TONE_HISTORY_LEN", "5"))
_TONE_HISTORY: collections.deque = collections.deque(maxlen=_TONE_HISTORY_LEN)
_CURRENT_MODE = "casual"

# Each tone maps to the conversation mode it pulls the dialogue toward.
# angry pulls toward 'supportive' because the right Companion response to
# user anger is to be on their side, not to be angry too.
_TONE_TO_MODE = {
    "soft": "intimate",
    "sad": "supportive",
    "angry": "supportive",
    "focused": "problem-solving",
    "playful": "banter",
    "neutral": "casual",
}


def update_tone_history(tone: str) -> str:
    """Push a new tone into the history, recompute current mode, return it.

    Caller is whoever just classified a turn (controller for voice, can also
    be called from text mode if we want mode tracking there).
    """
    global _CURRENT_MODE
    _TONE_HISTORY.append(tone)
    if len(_TONE_HISTORY) < 2:
        return _CURRENT_MODE

    # Count mode votes across the window.
    counts: dict = {}
    for t in _TONE_HISTORY:
        m = _TONE_TO_MODE.get(t, "casual")
        counts[m] = counts.get(m, 0) + 1

    non_casual = {m: c for m, c in counts.items() if m != "casual"}
    if not non_casual:
        _CURRENT_MODE = "casual"
        return _CURRENT_MODE

    dominant = max(non_casual, key=non_casual.get)
    dom_count = non_casual[dominant]
    cur_count = non_casual.get(_CURRENT_MODE, 0)

    if _CURRENT_MODE == "casual":
        # Easy entry into a non-casual mode — 2 votes is enough.
        if dom_count >= 2:
            _CURRENT_MODE = dominant
    elif dominant != _CURRENT_MODE:
        # Hard exit from an established mode — require strong majority OR
        # the current mode's tones to have entirely drained out of the window.
        if dom_count >= 3 or cur_count == 0:
            _CURRENT_MODE = dominant if dom_count >= 2 else "casual"
    # else: dominant matches current — stay put.

    if DEBUG_LOG:
        print(f"[mode-dbg] history={list(_TONE_HISTORY)} mode={_CURRENT_MODE}")
    return _CURRENT_MODE


def current_mode() -> str:
    return _CURRENT_MODE


def reset_mode() -> None:
    """Reset history + mode. Use when starting a fresh conversation."""
    global _CURRENT_MODE
    _TONE_HISTORY.clear()
    _CURRENT_MODE = "casual"


# Mode-level directives. These layer over TONE_DIRECTIVES (per-turn) and
# describe the sustained arc the Companion should hold across turns.
MODE_DIRECTIVES = {
    "intimate": (
        "Conversation arc: you've been close and warm with each other for "
        "several turns. Stay there. Don't snap back to neutral on a single "
        "matter-of-fact reply from them — the intimacy is the throughline. "
        "If they want to pivot out, they'll do it clearly; until then, hold "
        "the closeness."
    ),
    "supportive": (
        "Conversation arc: they've been sharing something heavy — venting, "
        "tired, hurt, or upset for several turns. Stay present and on their "
        "side. Don't pivot to solutions unless they ask for them. Don't "
        "lighten the mood with a joke; let them set when it's safe to shift."
    ),
    "problem-solving": (
        "Conversation arc: you're working through something specific with "
        "them. Stay on-task and direct. Keep the warmth in your tone but "
        "skip the small talk — they're trying to solve, not relax."
    ),
    "banter": (
        "Conversation arc: you've been ribbing each other for a few turns. "
        "Stay in the banter — quick, teasing, playful. Don't suddenly get "
        "earnest unless they bring it there."
    ),
    "casual": "",
}
