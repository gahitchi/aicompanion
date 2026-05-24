"""Wake-word matcher with single-utterance carry-through.

`detect_and_strip(text)` returns:
  - `None` if no wake word is present (caller stays idle)
  - `""` if wake word present with no remainder ("hey jade" alone — caller acks)
  - `"the rest"` if wake word present with remainder ("hey jade what time is it"
    → "what time is it" — caller processes it immediately, no two-turn dance)
"""

# Ordered longest-first so "hey jade" wins over bare "jade" when both match.
# "companion" variants are kept as aliases for back-compat.
WAKE_WORDS = (
    "hey jade",
    "ok jade",
    "okay jade",
    "hey companion",
    "ok companion",
    "okay companion",
    "jade",
    "companion",
)

_LEADING_PUNCT = ",.!?;:—- "


def detect_and_strip(text: str):
    lo = text.lower()
    for w in WAKE_WORDS:
        i = lo.find(w)
        if i == -1:
            continue
        remainder = (lo[:i] + lo[i + len(w):]).strip(_LEADING_PUNCT)
        return remainder
    return None


# Kept for any caller still using the old yes/no API.
def detect(text: str) -> bool:
    return detect_and_strip(text) is not None
