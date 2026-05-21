WAKE_WORDS = {

    "companion",
    "hey companion",
    "ok companion"

}


def detect(text):

    for word in WAKE_WORDS:

        if word in text:
            return True

    return False