from memory.vector_memory import search as vector_search
from memory.graph_memory import get_graph


def retrieve_context(query):

    vector = vector_search(query)

    graph = get_graph()

    return {
        "semantic_memory": vector,
        "graph_memory": graph
    }


def store_relation(entity_a, entity_b, relation, graph_memory):

    from memory.graph_memory import add_edge, add_node

    add_node(entity_a, {"type": "entity"})
    add_node(entity_b, {"type": "entity"})

    add_edge(entity_a, entity_b, relation)