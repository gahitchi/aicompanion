from fastapi import FastAPI
from state import history

app = FastAPI()


@app.get("/chat")
def get_chat():

    return history