import redis
import json

r = redis.Redis(host="localhost", port=6379, decode_responses=True)


STREAM = "agent_stream"


def publish(event):

    r.xadd(STREAM, {"data": json.dumps(event)})


def consume(last_id="0"):

    return r.xread({STREAM: last_id})