import asyncio
import logging
import os
from pathlib import Path

import aiohttp
import redis.asyncio as aioredis
from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    TurnHandlingOptions,
    cli,
)
from livekit.plugins import deepgram, google, silero

from interview_state import InterviewState
from interview_timer import close_when_quiet, run_timer
from interview_tools import LIMIT_SECONDS, WRAPUP_SECONDS, InterviewTools, build_tools
from plan_client import application_id_from_room, fetch_plan
from prompts import build_instructions

logger = logging.getLogger("interviewer")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

server = AgentServer()


class Interviewer(Agent):
    def __init__(self, instructions: str, tools: list | None = None):
        super().__init__(instructions=instructions, tools=tools or [])


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    application_id = application_id_from_room(ctx.job.room.name)
    plan = await fetch_plan(application_id) if application_id else None
    logger.info(
        "plan loaded: %s questions",
        len(plan["questions"]) if plan else "no",
    )

    state = None
    snap = None
    redis_client = None
    if plan and application_id:
        try:
            redis_client = aioredis.Redis.from_url(
                os.environ["REDIS_URL"],
                decode_responses=True,
                socket_connect_timeout=2,
            )
            state = InterviewState(redis_client, application_id, len(plan["questions"]))
            snap = await state.load_or_create()
            logger.info(
                "state: question %d/%d, followups %d, active %ds, status %s",
                min(snap.current_index + 1, snap.total_questions),
                snap.total_questions,
                snap.followups_used,
                snap.active_seconds,
                snap.status,
            )
        except Exception:
            logger.exception("could not load interview state; continuing without it")
            state = None
            snap = None

    async def close_redis():
        if redis_client:
            await redis_client.aclose()

    ctx.add_shutdown_callback(close_redis)

    background: set[asyncio.Task] = set()

    def spawn(coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)
        return task

    def on_closed():
        spawn(close_when_quiet(session))

    if state:
        logic = InterviewTools(state, plan["questions"], on_closed=on_closed)
        agent = Interviewer(build_instructions(plan, use_tools=True), build_tools(logic))
        logger.info("interviewer mode: tools")
    else:
        agent = Interviewer(build_instructions(plan))
        logger.info("interviewer mode: no-tools fallback")

    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=google.LLM(model="gemini-3.5-flash"),
        tts=deepgram.TTS(model="aura-2-thalia-en"),
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            endpointing={"mode": "fixed", "min_delay": 0.9, "max_delay": 3.5},
        ),
    )
    await session.start(agent=agent, room=ctx.room)

    if state:
        spawn(run_timer(state, session, LIMIT_SECONDS, WRAPUP_SECONDS))

    async def stop_background():
        for task in list(background):
            task.cancel()

    ctx.add_shutdown_callback(stop_background)

    async def save_transcript():
        if application_id is None:
            return
        entries = []
        for item in session.history.items:
            if getattr(item, "type", None) != "message":
                continue
            if item.role not in ("user", "assistant"):
                continue
            text = (item.text_content or "").strip()
            if text:
                role = "candidate" if item.role == "user" else "interviewer"
                entries.append({"role": role, "text": text})

        url = f"{os.getenv('API_URL', 'http://localhost:8000')}/internal/applications/{application_id}/transcript"
        try:
            async with aiohttp.ClientSession() as http:
                res = await http.post(
                    url,
                    json={"entries": entries},
                    headers={"X-Internal-Key": os.environ["INTERNAL_API_KEY"]},
                )
                logger.info("transcript save: %s (%d entries)", res.status, len(entries))
        except Exception:
            logger.exception("could not save transcript")

    ctx.add_shutdown_callback(save_transcript)

    if snap and snap.current_index > 0:
        greeting = (
            "Welcome the candidate back in one short sentence, say you will continue "
            "where you left off, then call next_question."
        )
    else:
        greeting = (
            "Greet the candidate in one short sentence and ask them to briefly "
            "introduce themselves."
        )
    await session.generate_reply(instructions=greeting)


if __name__ == "__main__":
    cli.run_app(server)