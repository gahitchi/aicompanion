TOOLS = {}


def register(name):

    def wrapper(fn):
        TOOLS[name] = fn
        return fn

    return wrapper


def run(name, *args, **kwargs):

    if name not in TOOLS:
        return "tool_not_found"

    return TOOLS[name](*args, **kwargs)