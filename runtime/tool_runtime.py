TOOLS = {}


def register(name):

    def wrap(fn):
        TOOLS[name] = fn
        return fn

    return wrap


def execute(name, *args, **kwargs):

    if name not in TOOLS:
        return {"error": "tool_not_found"}

    return TOOLS[name](*args, **kwargs)