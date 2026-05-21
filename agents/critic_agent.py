import json

def evaluate(model_client, model, task, result):

    prompt = {
        "task": task,
        "result": result,
        "instruction": "Rate quality 1-10 and detect errors"
    }

    res = model_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": json.dumps(prompt)}],
        temperature=0.2
    )

    return res.choices[0].message.content