import chromadb
import uuid

client = chromadb.PersistentClient(path="./memory_db")

collection = client.get_or_create_collection(
    name="vector_memory"
)


def add(text, embedding_func, weight=5):

    emb = embedding_func([text])[0]

    collection.add(
        documents=[text],
        embeddings=[emb],
        ids=[str(uuid.uuid4())],
        metadatas=[{"weight": weight}]
    )


def search(query, k=5):

    res = collection.query(
        query_texts=[query],
        n_results=k
    )

    return res["documents"][0] if res["documents"] else []