import chromadb
import uuid

client = chromadb.PersistentClient(path="./memory_db")
col = client.get_or_create_collection("memory")


def add(text):

    col.add(
        documents=[text],
        ids=[str(uuid.uuid4())]
    )


def search(query, k=5):

    res = col.query(
        query_texts=[query],
        n_results=k
    )

    if not res["documents"]:
        return ""

    return "\n".join(res["documents"][0])