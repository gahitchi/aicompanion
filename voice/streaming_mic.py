import sounddevice as sd
import numpy as np


SAMPLE_RATE = 16000
BLOCK_SIZE = 8000


def audio_stream():

    while True:

        audio = sd.rec(BLOCK_SIZE, samplerate=SAMPLE_RATE, channels=1, dtype='int16')
        sd.wait()

        yield np.array(audio)