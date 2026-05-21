def evaluate(task, result):

    score = 5

    if len(result) > 20:
        score += 2

    if "error" in result.lower():
        score -= 3

    return {
        "score": max(1, min(10, score)),
        "approved": score >= 5
    }