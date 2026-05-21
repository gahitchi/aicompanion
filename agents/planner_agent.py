import json

def run_planner(model_client, model, task, memory):

    prompt = {
        "task": task,
        "memory": memory,
        "instruction": "Break the task into clear actionable steps"
    }

    res = model_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": json.dumps(prompt)}],
        temperature=0.2
    )

    return res.choices[0].message.content