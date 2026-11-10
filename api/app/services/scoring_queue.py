"""A small reliable queue on Redis for scoring jobs.

enqueue  -> adds the application id once (a set stops duplicates while it is waiting)
reserve  -> moves the next id to a processing list, so a crashed worker loses nothing
ack      -> removes it from processing when done
requeue_stale -> at worker start, puts unfinished ids back (assumes one worker)
"""

import redis

from app.config import settings

QUEUE = "scoring:queue"
PROCESSING = "scoring:processing"
PENDING = "scoring:pending"


class ScoringQueue:
    def __init__(self, client=None):

        self.r = client or redis.Redis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=30
        )

    def enqueue(self, application_id: str) -> bool:
        if self.r.sadd(PENDING, application_id):
            self.r.lpush(QUEUE, application_id)
            return True
        return False

    def reserve(self, timeout: int = 5) -> str | None:
        return self.r.blmove(QUEUE, PROCESSING, timeout, src="RIGHT", dest="LEFT")

    def ack(self, application_id: str) -> None:
        self.r.lrem(PROCESSING, 1, application_id)
        self.r.srem(PENDING, application_id)

    def requeue_stale(self) -> int:
        count = 0
        # dest RIGHT = the end jobs are taken from, so an interrupted job is retried first
        while self.r.lmove(PROCESSING, QUEUE, src="RIGHT", dest="RIGHT"):
            count += 1
        return count
