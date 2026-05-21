import uvicorn
from api.gateway import app


if __name__ == "__main__":

    print("FULL AI PLATFORM ONLINE")

    uvicorn.run(app, host="0.0.0.0", port=8000)