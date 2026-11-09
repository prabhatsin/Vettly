import asyncio
import logging
import time

logger = logging.getLogger("interview_timer")

TICK_SECONDS = 5
TIME_UP_TEXT = (
    "We have reached the time limit for this interview, so I will stop here. "
    "Thank you for your time, and goodbye."
)


async def close_when_quiet(session, timeout: float = 30.0):
    """Wait for the goodbye to finish playing, then close the session."""
    await asyncio.sleep(1.5)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline and getattr(session, "agent_state", "listening") in (
        "thinking",
        "speaking",
    ):
        await asyncio.sleep(0.3)
    logger.info("closing session after goodbye")
    session.shutdown(drain=True)


async def run_timer(state, session, limit_seconds: float, wrapup_seconds: float):
    """Count connected time. Flag wrap-up near the limit, and stop the interview at it."""
    last = time.monotonic()
    wrapup_sent = False
    while True:
        await asyncio.sleep(TICK_SECONDS)
        now = time.monotonic()
        total = await state.tick(now - last)
        last = now
        if total is None:
            return

        remaining = limit_seconds - total
        if remaining <= wrapup_seconds and not wrapup_sent:
            await state.set_wrapup()
            wrapup_sent = True
            logger.info("wrap-up time reached (%ds left)", remaining)

        if remaining <= 0:
            logger.info("time limit reached; closing")
            await session.say(TIME_UP_TEXT, allow_interruptions=False)
            await state.end()
            session.shutdown(drain=True)
            return

