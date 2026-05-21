import requests


OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3"


def chat(prompt, context=""):

    full_prompt = f"""
You are a persistent AI companion.

Context:
{context}

User:
{prompt}

Respond naturally and briefly.
"""

    r = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "prompt": full_prompt,
        "stream": False
    })

    return r.json()["response"]