import queue
import json
import sounddevice as sd

from vosk import Model
from vosk import KaldiRecognizer

audio_queue = queue.Queue()

MODEL = Model("models/vosk")

recognizer = KaldiRecognizer(
    MODEL,
    16000
)


def callback(indata, frames, time, status):

    audio_queue.put(
        bytes(indata)
    )


def stream_recognition():

    with sd.RawInputStream(
        samplerate=16000,
        blocksize=8000,
        dtype='int16',
        channels=1,
        callback=callback
    ):

        while True:

            data = audio_queue.get()

            if recognizer.AcceptWaveform(data):

                result = json.loads(
                    recognizer.Result()
                )

                text = result.get(
                    "text",
                    ""
                )

                if text:

                    yield text.lower()