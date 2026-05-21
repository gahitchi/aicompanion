from core.broker import push_task


def plan(task):

    steps = [
        f"analyze:{task}",
        f"execute:{task}",
        f"validate:{task}"
    ]

    for s in steps:
        push_task({
            "type": "step",
            "content": s
        })

    return steps