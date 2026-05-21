from memory.graph_memory import get_graph


def propagate():

    graph = get_graph()

    scores = {n: 1.0 for n in graph["nodes"]}

    for edge in graph["edges"]:

        src = edge["from"]
        dst = edge["to"]

        scores[dst] = scores.get(dst, 1.0) + 0.5 * scores.get(src, 1.0)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def retrieve_top_k(k=5):

    ranked = propagate()

    return ranked[:k]