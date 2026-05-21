import speech_recognition as sr
import pyttsx3

tts = pyttsx3.init()


def speak(text):
    tts.say(text)
    tts.runAndWait()


def listen():

    r = sr.Recognizer()

    with sr.Microphone() as source:
        print("Listening...")
        audio = r.listen(source)

    try:
        return r.recognize_google(audio)

    except:
        return ""