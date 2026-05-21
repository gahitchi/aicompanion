import chromadb
import uuid
from sklearn.cluster import KMeans
import numpy as np

client = chromadb.PersistentClient(path="./memory_db")

collection = client.get_or_create_collection(
    name="semantic_memory"
)


def add_memory(text, embedding_func, importance=5):

    emb = embedding_func([text])[0]

    collection.add(
        documents=[text],
        embeddings=[emb],
        ids=[str(uuid.uuid4())],
        metadatas=[{"importance": importance}]
    )


def get_all():

    data = collection.get(include=["embeddings", "documents"])

    return data


def cluster_memories(n_clusters=5):

    data = get_all()

    if not data["embeddings"]:
        return {}

    X = np.array(data["embeddings"])

    kmeans = KMeans(n_clusters=n_clusters, n_init=10)
    labels = kmeans.fit_predict(X)

    clusters = {}

    for label, doc in zip(labels, data["documents"]):
        clusters.setdefault(int(label), []).append(doc)

    return clusters