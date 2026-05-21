import chromadb
import uuid

client = chromadb.PersistentClient(path="./db/vector")

col = client.get_or_create_collection("memory")


def store_vector(text):

    col.add(
        documents=[text],
        ids=[str(uuid.uuid4())]
    )


def search(query, k=5):

    res = col.query(
        query_texts=[query],
        n_results=k
    )

    return res["documents"][0]