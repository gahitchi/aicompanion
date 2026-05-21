import networkx as nx
import json

G = nx.DiGraph()


def add_node(node):

    G.add_node(node)


def add_relation(a, b, relation):

    G.add_edge(a, b, type=relation)


def query_top():

    return list(G.nodes)


def save_graph():

    nx.write_gexf(G, "graph.gexf")


def load_graph():

    global G

    G = nx.read_gexf("graph.gexf")