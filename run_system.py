import multiprocessing
import uvicorn

from workers.worker import run_worker
from api.main import app


def start_api():

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":

    processes = []

    # API
    p = multiprocessing.Process(target=start_api)
    p.start()
    processes.append(p)

    # Workers (swarm)
    for i in range(4):

        p = multiprocessing.Process(
            target=run_worker,
            args=(i,)
        )

        p.start()
        processes.append(p)

    for p in processes:
        p.join()