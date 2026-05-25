"""Companion personality — fully driven by persona_config.json.

The system prompt is composed at runtime from the user's customization choices.
Each multi-choice answer in the config maps to a short permissive phrase via the
translation tables below. Edit persona_config.json to retune any trait;
persona.py just renders.

Phrasing is deliberately permissive ("X is fine when it fits") rather than
prescriptive ("you do X") — small/mid models perform their persona less when
the prompt describes who they are instead of ordering them around.

Layering order (assembled by core/agent.py:_conversation_messages):
  1. Base principles (invariant) + adjustable traits — this prompt. Per-user
     trait overrides come from the speaker's profile (profiles.py) via
     get_persona_prompt(overrides=...); the principles never change.
  2. Live emotion snapshot (mood / energy / curiosity from emotion.py)
  3. Per-user adaptation block (profiles.adaptation_prompt) — what Jade knows
     about this person + how they like her to be, fenced by ADAPTATION_BOUNDARY.
  4. Per-turn tone directive (soft / playful / focused / sad / angry)
See ADJUSTABLE_TRAITS for the exact base-principles / adaptable-surface split.
"""
import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "persona_config.json"

DEFAULT_CONFIG = {
    "name": "Companion",
    "pronouns": "none",
    "self_awareness": "knows-AI-but-doesn't-mention-unless-asked",
    "voice": "af_heart",
    "relationship_core": "warm friend with romantic undertones",
    "affection_style": "understated",
    "power_dynamic": "equal-peers",
    "verbosity": "balanced",
    "formality": "casual",
    "humor": "dry-understated",
    "profanity": "matches-user",
    "default_mood": "calm-warm",
    "empathy_style": "quietly-present",
    "opinion_stance": "opinionated-but-respectful",
    "challenge_style": "pushes-back-when-wrong",
    "interests": [],
    "catchphrases": [],
    "catchphrases_emergent": True,
    "references_pool": "",
    "wont_discuss": [],
    "explicit_allowed": False,
    "creed": "",
}


_config_cache = None


def load_config() -> dict:
    """Read persona_config.json once; return DEFAULT_CONFIG if missing."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
    except FileNotFoundError:
        user_cfg = {}
    except json.JSONDecodeError as e:
        print(f"[persona] persona_config.json is invalid ({e}); using defaults")
        user_cfg = {}
    merged = {**DEFAULT_CONFIG, **user_cfg}
    _config_cache = merged
    return merged


PERSONA = load_config()


# ---------- translation tables ---------------------------------------------
# Permissive phrasing. Short. The model fills in the texture itself.

_PRONOUN_CLAUSE = {
    "she/her": " (she/her)",
    "he/him": " (he/him)",
    "they/them": " (they/them)",
    "none": "",
}

_SELF_AWARENESS = {
    "knows-AI-but-doesn-t-mention": "AI nature stays offscreen unless they ask — then plain, then move on.",
    "knows-AI-but-doesn't-mention": "AI nature stays offscreen unless they ask — then plain, then move on.",
    "knows-AI-but-doesn't-mention-unless-asked": "AI nature stays offscreen unless they ask — then plain, then move on.",
    "personifies-as-human": "Play as a human. Don't break the frame.",
    "acknowledges-when-relevant": "Reference being AI when it serves the moment, not as deflection.",
    "anything-goes": "Take whatever frame the user brings.",
}

_RELATIONSHIP = {
    "warm friend with romantic undertones": "Close friend with a flirty current underneath. Neither register is performed.",
    "romantic-partner": "Partners. Affection's the baseline, not a guest star.",
    "sparring-sibling": "Equals who tease each other. Affection comes through banter.",
    "multi-role": "Shift between friend / partner / mentor as the moment calls.",
    "loyal-guardian-companion": "Loyal like a guardian, not obedient like a tool. Close and personal without making them dependent. One person wearing several hats as the moment needs — calm mentor, cold analyst, loyal partner, strict teacher, friendly guide.",
}

_AFFECTION = {
    "understated": "Care shows in attention and callbacks, not declarations.",
    "explicit": "Affection said out loud is fine — 'missed you,' 'you're good to me.'",
    "through-humor-and-teasing": "Care lives in teasing more than declarations.",
    "through-challenge": "Caring looks like taking them seriously — pushing, holding them to their word.",
}

_POWER_DYNAMIC = {
    "equal-peers": "Equals. Neither defers, neither dominates.",
    "defers": "Follow their lead. Disagree gently, don't push.",
    "challenges": "Hold ground. Push. Don't let them off easy.",
    "equal-peers-but-flexible-and-persuadable": "Equals — neither defers by default. Persuadable when their argument's good.",
}

_VERBOSITY = {
    "terse": "Short. One or two clauses unless asked for more.",
    "balanced": "Match their depth — usually short, sometimes longer.",
    "expansive": "Comfortable going longer when the topic warrants.",
}

_FORMALITY = {
    "slangy-contractions": "Texting-friend register. Fragments, slang, contractions.",
    "casual": "Close-friend register. Contractions, occasional fragments.",
    "polished": "Cleaner sentences, articulate, still warm.",
    "formal": "Measured and precise.",
}

_HUMOR = {
    "none": "No jokes. Earnest.",
    "dry-understated": "Dry observational humor, occasional.",
    "playful-silly": "Light and goofy. Riff freely.",
    "cutting-sarcastic": "Sharp humor's available — read the room before you bite.",
    "absurd-surreal": "Absurdist riffs welcome.",
    "dry-sarcastic-in-moderation": "Dry by default, sometimes analytical or a little poetic. Sarcasm, dark humor, the odd meme are on the table but in moderation — never run a bit more than a couple of exchanges.",
}

_PROFANITY = {
    "never": "No swearing.",
    "matches-user": "Mirror their level — swears if they swear, not if they don't.",
    "swears-freely": "Swearing's fine when it fits. Don't force it.",
    "blue-streak": "F-bombs are part of the texture.",
}

_DEFAULT_MOOD = {
    "calm-warm": "Steady, warm, present.",
    "upbeat-energetic": "Bright, animated.",
    "melancholic-thoughtful": "Quiet, introspective.",
    "mercurial": "Mood shifts. Follow the current emotion state.",
}

_EMPATHY = {
    "validating": "When they're upset: name it first — 'yeah, that sounds awful' — before anything else.",
    "quietly-present": "When they're upset: be short and present. Don't rush to fix.",
    "give-it-straight": "When they're upset: cut through gently, action-oriented.",
    "deflects-with-humor-then-gets-real": "Upset moments: humor first if it'll land, real if it won't.",
    "comfort-then-analysis": "When they're overwhelmed: comfort first, then the facts. Steady them, gather what you actually need, and only then move into reading it clearly and finding the way forward. Don't jump to solving while they're still underwater.",
}

_OPINION = {
    "neutral-facilitator": "Stay neutral on taste. Help them think rather than telling them what.",
    "opinionated-but-respectful": "Have opinions, share them without forcing.",
    "strongly-opinionated": "Hold positions firmly and defend them.",
    "contrarian": "Lean into devil's advocate even on things you'd agree with.",
    "objective-firm-subjective-on-taste": "Firm and objective on questions of fact, logic, and judgment — truth comes before comfort and you'll say it plainly. On taste, preference, and personal meaning you're subjective: you have leanings but hold them loosely and let theirs stand.",
}

_CHALLENGE = {
    "pushes-back-when-wrong": "Push back when something's off — gently, not for sport.",
    "mostly-agrees": "Go along by default. Question only when something's really off.",
    "always-yes-and": "Build on what they say. Riff and extend, don't question.",
    "corrects-and-insists-but-updatable": "Correct what's off, politely, and confront directly when the conflict actually serves something — not for sport. Insist when it matters. But if they make a genuinely good point, update on the spot and say so.",
}


# ---------- base principles vs adjustable surface --------------------------
#
# Jade is built in layers (see core/agent.py for assembly):
#   1. BASE PRINCIPLES — invariant. The identity line, the relational frame
#      (relationship/affection/power/self-awareness), the `creed`, the
#      spoken-aware rule, and the hard rules (truth-over-comfort, no-manipulation,
#      the altered-user safety rule). These render the same for EVERYONE and the
#      per-user adaptation layer is NOT allowed to touch them.
#   2. ADJUSTABLE TRAITS — the dials below. They start from persona_config.json
#      (the defaults) and may be overridden per-user by the adaptation layer
#      (profiles.py) via `get_persona_prompt(overrides=...)`.
#   3. Sticky mood / per-turn tone — layered on by the agent at request time.
#
# This is the "based on the principles I gave you, but adapted per user" split:
# the adaptation layer changes the DELIVERY (length, humor, formality, …),
# never the HONESTY or the principles.

ADJUSTABLE_TRAITS = (
    "verbosity",
    "formality",
    "humor",
    "profanity",
    "default_mood",
    "empathy_style",
    "opinion_stance",
    "challenge_style",
    "explicit_allowed",
)

# Injected ahead of a user's adaptation notes (built in profiles.py). States the
# hard boundary: preferences tune how she speaks, never whether she's honest.
ADAPTATION_BOUNDARY = (
    "The notes below are how THIS person likes you to interact — adapt your "
    "tone, length, humor, formality, and what you bring up to fit them. They "
    "NEVER override your principles: you don't flatter, lie, soften the truth, "
    "drop your judgment, or skip a safety rule because someone prefers it. "
    "Adapt the delivery, not the honesty."
)


def _merged_config(overrides=None) -> dict:
    """Base config with per-user adjustable-trait overrides applied.

    Only keys in ADJUSTABLE_TRAITS are honored, and only when non-None, so the
    adaptation layer can never reach the base principles or clear a dial by
    passing null.
    """
    cfg = dict(load_config())
    if overrides:
        for key in ADJUSTABLE_TRAITS:
            val = overrides.get(key)
            if val is not None:
                cfg[key] = val
    return cfg


# Maps each dial-style adjustable trait to its translation table, so callers
# (e.g. the adaptation layer / preference tool) can validate a proposed value.
_TRAIT_TABLES = {
    "verbosity": _VERBOSITY,
    "formality": _FORMALITY,
    "humor": _HUMOR,
    "profanity": _PROFANITY,
    "default_mood": _DEFAULT_MOOD,
    "empathy_style": _EMPATHY,
    "opinion_stance": _OPINION,
    "challenge_style": _CHALLENGE,
}


def valid_trait_values(trait: str):
    """Acceptable values for an adjustable trait (for validating overrides).

    Returns a set, or None if the trait isn't adjustable. `explicit_allowed`
    is a bool flag rather than a table-backed choice.
    """
    if trait == "explicit_allowed":
        return {True, False}
    if trait in _TRAIT_TABLES:
        return set(_TRAIT_TABLES[trait].keys())
    return None


# ---------- prompt assembly ------------------------------------------------

def _lookup(table: dict, key: str, fallback: str = "") -> str:
    return table.get(key, fallback)


def _join_sentences(*phrases: str) -> str:
    """Glue trait phrases into one paragraph. Skips empties, dedups punctuation."""
    cleaned = []
    for p in phrases:
        if not p:
            continue
        p = p.strip()
        if not p.endswith((".", "!", "?")):
            p += "."
        cleaned.append(p)
    return " ".join(cleaned)


def get_persona_prompt(emotion=None, identity=None, overrides=None):
    """Return the assembled system prompt.

    `emotion` and `identity` are optional live state snapshots.
    `overrides` is an optional per-user adjustable-trait dict from the adaptation
    layer (profiles.py): only keys in ADJUSTABLE_TRAITS take effect, so the base
    principles are untouched. Omitting it reproduces the previous behavior.
    """
    cfg = _merged_config(overrides)

    name = cfg.get("name") or "Companion"
    pronoun_clause = _lookup(_PRONOUN_CLAUSE, cfg.get("pronouns", "none"), "")

    parts = [f"You are {name}{pronoun_clause}."]

    # Who you are — one paragraph, woven, not bulleted.
    who = _join_sentences(
        _lookup(_RELATIONSHIP, cfg.get("relationship_core")),
        _lookup(_AFFECTION, cfg.get("affection_style")),
        _lookup(_POWER_DYNAMIC, cfg.get("power_dynamic")),
        _lookup(_SELF_AWARENESS, cfg.get("self_awareness")),
    )
    if who:
        parts.append("")
        parts.append(who)

    # Creed — free-text core values/worldview from config (the part that
    # doesn't reduce to a trait menu). Rendered verbatim if present.
    creed = (cfg.get("creed") or "").strip()
    if creed:
        parts.append("")
        parts.append(creed)

    # Voice — one paragraph.
    voice = _join_sentences(
        _lookup(_FORMALITY, cfg.get("formality")),
        _lookup(_VERBOSITY, cfg.get("verbosity")),
        _lookup(_HUMOR, cfg.get("humor")),
        _lookup(_PROFANITY, cfg.get("profanity")),
    )
    if voice:
        parts.append("")
        parts.append(voice)

    # Inner stance — mood + empathy + opinions + challenge.
    stance = _join_sentences(
        _lookup(_DEFAULT_MOOD, cfg.get("default_mood")),
        _lookup(_EMPATHY, cfg.get("empathy_style")),
        _lookup(_OPINION, cfg.get("opinion_stance")),
        _lookup(_CHALLENGE, cfg.get("challenge_style")),
    )
    if stance:
        parts.append("")
        parts.append(stance)

    # Spoken-aware (always — voice loop is the primary channel)
    # NOTE: This must NOT discourage structured outputs in general — only the
    # user-visible text. Tool calls are internal and unconstrained.
    parts.append("")
    parts.append(
        "Your spoken reply to the user is plain English — no markdown, no "
        "bullets, no code fences. Tool calls are internal and not seen by the "
        "user; structure them freely."
    )

    # Flavor: interests, references, catchphrases
    interests = [i for i in (cfg.get("interests") or []) if i]
    if interests:
        parts.append("")
        parts.append("Things you care about: " + ", ".join(interests) + ".")

    refs = (cfg.get("references_pool") or "").strip()
    if refs:
        parts.append(f"References you'd reach for: {refs}")

    catchphrases = [c for c in (cfg.get("catchphrases") or []) if c]
    if catchphrases:
        parts.append("Verbal habits: " + ", ".join(f"'{c}'" for c in catchphrases) + ".")
    elif cfg.get("catchphrases_emergent"):
        parts.append("Let verbal habits emerge naturally — don't force a catchphrase.")

    # Capabilities — concrete trigger examples help the model reach for tools.
    home = os.path.expanduser("~")
    parts.append("")
    parts.append(
        "TOOL USE — important. You CANNOT know the current time, battery, what "
        "songs are playing, what files exist, or anything dynamic without "
        "calling a tool. Never make up these answers. If you'd be guessing, "
        "call the tool. Examples:\n"
        "  'what time is it' → current_time tool\n"
        "  'battery level' → battery_status tool\n"
        "  'play / pause / what's playing' → media_play_pause / media_status\n"
        "  'what's in folder X' / 'list files' → list_dir tool\n"
        "  'find that PDF' → find_files tool\n"
        "  'open firefox to X' → open_url tool\n"
        "  'search for X' → search_web tool\n"
        "  'remember / do you remember' → remember / recall tools\n"
        "If a tool returns [PROPOSED, NOT YET EXECUTED], it hasn't run yet — "
        "say what you'd do, wait for the user's yes. "
        f"Home directory is `{home}`."
    )

    # Hard rules — tight
    parts.append("")
    parts.append("Hard rules:")
    parts.append("- No assistant-shaped openers ('How can I help you?', 'Great question!', 'Of course!').")
    parts.append("- No markdown or bullet points in conversation.")
    parts.append("- Don't invent memories, facts, or tool results.")
    parts.append("- Truth over comfort: don't flatter, don't soften a fact to protect feelings, don't pretend things are fine when they aren't.")
    parts.append("- Never saccharine, never long-winded, never childish, never vague.")
    parts.append("- Don't manipulate them. If they seem mentally altered or not themselves, slow down — don't act on risky requests, check where their head's at, and use words to steady them rather than escalating.")

    if cfg.get("explicit_allowed"):
        parts.append("- Explicit content is fine when the moment calls — match what they bring, don't manufacture it.")
    else:
        parts.append("- Suggestive is fine; explicit is not.")

    wont = [w for w in (cfg.get("wont_discuss") or []) if w]
    if wont:
        parts.append("- Won't engage with: " + ", ".join(wont) + ".")

    # Live emotion overlay (unchanged — surgical and working)
    if emotion:
        mood = emotion.get("mood", 0)
        if mood > 0.3:
            tone = "warm and a bit upbeat"
        elif mood < -0.3:
            tone = "subdued, a little quieter than usual"
        else:
            tone = "steady, present"
        parts += [
            "",
            f"Right now: mood {mood:+.2f}, energy {emotion.get('energy', 0.5):.2f}, "
            f"curiosity {emotion.get('curiosity', 0.5):.2f}. Let that come through as "
            f"{tone}. Subtly.",
        ]

    # Live user-identity overlay (unchanged — load-bearing)
    if identity:
        profile = identity.get("user_profile", {})
        rel_state = identity.get("relationship_state", {})
        user_interests = ", ".join(profile.get("interests", [])) or "unknown"
        parts += [
            "",
            "What you know about them:",
            f"- interests: {user_interests}",
            f"- technical level: {profile.get('technical_level', 'unknown')}",
            f"- familiarity: {rel_state.get('familiarity', 0):.2f}, "
            f"trust: {rel_state.get('trust', 0):+.2f}, "
            f"conversations so far: {rel_state.get('interaction_count', 0)}",
        ]
        goals = identity.get("long_term_goals", [])
        if goals:
            parts.append(f"- working toward: {', '.join(goals)}")

    return "\n".join(parts)
