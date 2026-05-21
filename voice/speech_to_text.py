import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import speech_recognition as sr


def listen_once():

    recognizer = sr.Recognizer()

    fs = 16000
    duration = 4

    print("Listening...")

    recording = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='int16')
    sd.wait()

    filename = "temp.wav"
    wav.write(filename, fs, recording)

    with sr.AudioFile(filename) as source:
        audio = recognizer.record(source)

    try:
        return recognizer.recognize_google(audio)

    except:
        return ""