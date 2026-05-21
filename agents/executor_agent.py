import json
from tools.filesystem import read_file, write_file
from tools.runner import run_command
from tools.web import search_web

def execute(task_json):

    t = task_json.get("type")

    if t == "tool":

        tool = task_json["tool"]
        args = task_json.get("args", {})

        if tool == "read_file":
            return read_file(**args)

        if tool == "write_file":
            return write_file(**args)

        if tool == "run_command":
            return run_command(**args)

        if tool == "search_web":
            return search_web(**args)

        return "Unknown tool"

    if t == "final":
        return task_json.get("content")

    return "Invalid execution request"