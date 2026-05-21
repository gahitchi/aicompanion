import json

def run(task, memory):

    return json.dumps({
        "steps": [
            f"analyze {task}",
            "decompose task",
            "execute subtasks",
            "validate output"
        ],
        "context": memory
    })