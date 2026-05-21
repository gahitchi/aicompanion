import webrtcvad

vad = webrtcvad.Vad(2)

def speech_present(frame, sample_rate=16000):

    try:
        return vad.is_speech(
            frame,
            sample_rate
        )

    except:
        return False