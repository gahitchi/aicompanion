from fastapi import FastAPI
import json

app = FastAPI()

GOALS_FILE = "goals.json"


@app.get("/goals")
def get_goals():

    try:
        return json.loads(open(GOALS_FILE).read())
    except:
        return []


@app.get("/memory")
def get_memory():

    from memory_engine import get_memory_summary

    return get_memory_summary()


@app.get("/clusters")
def clusters():

    from cluster_memory import cluster_memories

    return cluster_memories()