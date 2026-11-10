"""Scoring worker. Run from the api folder:  python -m app.worker"""

import asyncio
import logging
import uuid

from app.db.session import get_db
from app.repositories.scoring import ReportRepository
from app.services.scoring_queue import ScoringQueue
from app.services.scoring_runner import ScoringJob
import time
import redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("worker")


def process(application_id: str) -> None:
    """Score one application. Any error is stored on the report instead of crashing."""
    app_uuid = uuid.UUID(application_id)
    session_gen = get_db()
    db = next(session_gen)
    try:
        asyncio.run(ScoringJob(db).run(app_uuid))
    except Exception as exc:
        logger.exception("scoring failed for %s", application_id)
        db.rollback()
        ReportRepository(db).save(app_uuid, status="failed", error=str(exc)[:500])
    finally:
        session_gen.close()


def main() -> None:
    queue = ScoringQueue()
    back = queue.requeue_stale()
    if back:
        logger.info("requeued %d unfinished jobs", back)
    logger.info("worker ready")
    try:
        while True:

            try:
                application_id = queue.reserve(timeout=5)
            except (redis.exceptions.TimeoutError, redis.exceptions.ConnectionError):
                logger.warning("redis not reachable, retrying")
                time.sleep(2)
                continue

            if application_id is None:
                continue
            logger.info("scoring %s", application_id)
            process(application_id)
            queue.ack(application_id)
    except KeyboardInterrupt:
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
