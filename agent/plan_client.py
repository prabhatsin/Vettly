import logging
import os
import uuid

import aiohttp

logger = logging.getLogger("plan_client")


def application_id_from_room(room_name: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(room_name.removeprefix("interview-"))
    except ValueError:
        return None


async def fetch_plan(application_id: uuid.UUID) -> dict | None:
    base = os.getenv("API_URL", "http://localhost:8000")
    url = f"{base}/internal/applications/{application_id}/plan"
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            res = await http.post(
                url, headers={"X-Internal-Key": os.environ["INTERNAL_API_KEY"]}
            )
            if res.status != 200:
                logger.warning("plan fetch failed: HTTP %s", res.status)
                return None
            return await res.json()
    except Exception:
        logger.exception("plan fetch error")
        return None