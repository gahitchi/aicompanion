def decide_importance(text: str):

    score = 5

    if len(text) > 200:
        score += 2

    if "error" in text.lower():
        score -= 2

    if "success" in text.lower():
        score += 2

    return max(1, min(score, 10))