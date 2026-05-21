import json
import os

FILE = "graph.json"


def load():

    if not os.path.exists(FILE):
        return {"nodes": {}, "edges": []}

    return json.loads(open(FILE, "r").read())


def save(data):

    with open(FILE, "w") as f:
        f.write(json.dumps(data, indent=2))


def add_node(node_id, data):

    g = load()

    g["nodes"][node_id] = data

    save(g)


def add_edge(src, dst, relation):

    g = load()

    g["edges"].append({
        "from": src,
        "to": dst,
        "relation": relation
    })

    save(g)


def query_node(node_id):

    return load()["nodes"].get(node_id, None)


def get_graph():

    return load()