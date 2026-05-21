import json
from openai import OpenAI
from memory import save_memory, get_memories

MODEL = "qwen2.5:7b-instruct"

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"
)

SYSTEM_PROMPT = """
You are a smart, useful, slightly sharp AI companion.

Rules:
- Be intelligent first, witty second.
- Use dry humor lightly, not constantly.
- Stay helpful, direct, and concise.
- Ask clarifying questions only when needed.
- Never invent tool outputs or memory.
- Treat memory as useful context, not truth.
- Remember stable user preferences.
- English only.
"""

def extract_memories(user_input: str, answer: str) -> None:
    prompt = f"""
Extract up to 3 stable, useful, non-sensitive memory facts from this exchange.
Return ONLY a JSON array of strings.
If nothing should be stored, return [].

User: {user_input}
Assistant: {answer}
"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        data = json.loads(resp.choices[0].message.content.strip())
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str) and item.strip():
                    save_memory(item.strip(), kind="profile")
    except Exception:
        pass

def reply(user_input: str, history: list[dict]) -> str:
    memories = get_memories(user_input)
    memory_text = "\n".join(f"- {m}" for m in memories) if memories else "- none"

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + "\n\nRelevant memory:\n" + memory_text
        }
    ]

    messages.extend(history[-12:])
    messages.append({"role": "user", "content": user_input})

    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.7
    )

    answer = resp.choices[0].message.content.strip()

    save_memory(f"User said: {user_input}", kind="event")
    extract_memories(user_input, answer)

    return answer