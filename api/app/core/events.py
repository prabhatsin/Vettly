"""Live updates: publish an event to one user's Redis channel. The SSE endpoint relays it."""
import json
import logging

import redis

from app.config import settings

logger = logging.getLogger("uvicorn.error")
_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
    return _client


def publish(user_id, event: dict) -> None:
    """Best effort: a Redis outage must not break the request that triggered it."""
    try:
        _redis().publish(f"user:{user_id}", json.dumps(event, default=str))
    except redis.RedisError:
        logger.warning("live publish failed for user %s", user_id)