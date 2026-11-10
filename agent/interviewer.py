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
    RunContext,
    TurnHandlingOptions,
    cli,
    function_tool,
)
from livekit.plugins import  google, silero
from livekit.plugins import gnani

from interview_state import InterviewState
from interview_timer import close_when_quiet, run_timer
from interview_tools import LIMIT_SECONDS, WRAPUP_SECONDS, InterviewTools, build_tools
from plan_client import application_id_from_room, fetch_plan
from prompts import STAGE_NOTES, build_instructions
from session_data import STAGES, SessionData, split_ranges

logger = logging.getLogger("interviewer")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

server = AgentServer()

INTRO = "Greet the candidate in one short sentence and ask them to briefly introduce themselves."
LEADS = {
    "technical": "Say one short, natural transition sentence into the technical part of the conversation. Do not greet again.",
    "behavioral": "Say one short, natural transition sentence into the scenario and experience part of the conversation. Do not greet again.",
    "screener": "Say one short sentence.",
}
REJOIN_LEAD = "Welcome the candidate back in one short sentence and say you will continue where you left off."


class Interviewer(Agent):
    """Single-agent fallback used when Redis state is unavailable."""

    def __init__(self, instructions: str, tools: list | None = None):
        super().__init__(instructions=instructions, tools=tools or [])


class StageAgent(Agent):
    stage = "screener"

    def __init__(self, data: SessionData, rejoin: bool = False):
        self.data = data
        self.rejoin = rejoin
        _, end = data.ranges[self.stage]
        self.logic = InterviewTools(
            data.state, data.plan["questions"],
            stage=self.stage, stage_end=end, on_closed=data.on_closed,
        )
        tools = build_tools(self.logic)
        if self.stage != STAGES[-1]:
            tools.append(make_stage_done(self.logic, data))

        instructions = build_instructions(data.plan, use_tools=True) + STAGE_NOTES[self.stage]
        done = [f"- {s}: {t}" for s, t in data.summaries.items() if s != self.stage]
        if done:
            instructions += (
                "\nAlready covered earlier in this call (never re-ask these topics):\n"
                + "\n".join(done)
            )
        super().__init__(instructions=instructions, tools=tools)

    async def on_enter(self):
        if self.stage == "screener" and not self.rejoin:
            await self.session.generate_reply(instructions=INTRO)
            return
        lead = REJOIN_LEAD if self.rejoin else LEADS[self.stage]
        try:
            first = await self.logic.next_question()
        except Exception:
            first = "Continue the interview."
        await self.session.generate_reply(instructions=f"{lead}\n\n{first}")


class ScreenerAgent(StageAgent):
    stage = "screener"


class TechnicalAgent(StageAgent):
    stage = "technical"


class BehavioralAgent(StageAgent):
    stage = "behavioral"


AGENTS = {"screener": ScreenerAgent, "technical": TechnicalAgent, "behavioral": BehavioralAgent}


def make_stage_done(logic: InterviewTools, data: SessionData):
    @function_tool()
    async def stage_done(context: RunContext, summary: str):
        """Hand the call to the next interviewer once this stage's questions are all done.
        Say nothing to the candidate yourself; the next interviewer continues the call.

        Args:
            summary: 2-3 sentences on what you learned about the candidate in this stage.
        """
        logger.info("tool: stage_done (%s)", logic.stage)
        nxt, advanced = await logic.complete_stage(summary)
        if not advanced:
            return "Already handed off. Say nothing more."
        data.summaries[logic.stage] = summary.strip()[:600]
        data.stage = nxt
        logger.info("handoff: %s -> %s", logic.stage, nxt)
        return AGENTS[nxt](data), f"Handed off to the {nxt} stage."

    return stage_done


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    application_id = application_id_from_room(ctx.job.room.name)
    plan = await fetch_plan(application_id) if application_id else None
    logger.info("plan loaded: %s questions", len(plan["questions"]) if plan else "no")

    state = None
    snap = None
    redis_client = None
    if plan and application_id:
        try:
            redis_client = aioredis.Redis.from_url(
                os.environ["REDIS_URL"], decode_responses=True, socket_connect_timeout=2,
            )
            state = InterviewState(redis_client, application_id, len(plan["questions"]))
            snap = await state.load_or_create()
            logger.info(
                "state: question %d/%d, followups %d, active %ds, status %s",
                min(snap.current_index + 1, snap.total_questions),
                snap.total_questions, snap.followups_used, snap.active_seconds, snap.status,
            )
        except Exception:
            logger.exception("could not load interview state; continuing without it")
            state = None
            snap = None

    ended = {"value": False}
    async def refresh_ended():
       if state is None:
           return
       try:
           now = await state.snapshot()
           if now is not None and now.status == "ended":
               ended["value"] = True
       except Exception:
           pass

    async def close_redis():
        await refresh_ended()
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

    data = None
    if state:
        data = SessionData(
            application_id=application_id,
            plan=plan,
            ranges=split_ranges(len(plan["questions"])),
            stage=await state.get_stage(),
            summaries=await state.summaries(),
            state=state,
            on_closed=on_closed,
        )
        agent = AGENTS[data.stage](data, rejoin=bool(snap and snap.current_index > 0))
        logger.info("interviewer mode: staged, starting at %s", data.stage)
    else:
        agent = Interviewer(build_instructions(plan))
        logger.info("interviewer mode: no-tools fallback")

    session = AgentSession[SessionData](
        stt=gnani.STT(language="en-IN"),
        llm=google.LLM(model="gemini-3.5-flash"),
        tts=gnani.TTS(voice="Pranav",synthesize_method="websocket"),
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            endpointing={"mode": "fixed", "min_delay": 0.9, "max_delay": 3.5},
        ),
        userdata=data,
    )
    await session.start(agent=agent, room=ctx.room)

    if state:
        spawn(run_timer(state, session, LIMIT_SECONDS, WRAPUP_SECONDS))

    async def stop_background():
        for task in list(background):
            task.cancel()

    ctx.add_shutdown_callback(stop_background)

    async def save_transcript():
        await refresh_ended()
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
                    json={"entries": entries, "ended": ended["value"]},
                    headers={"X-Internal-Key": os.environ["INTERNAL_API_KEY"]},
                )
                logger.info("transcript save: %s (%d entries)", res.status, len(entries))
        except Exception:
            logger.exception("could not save transcript")

    ctx.add_shutdown_callback(save_transcript)

    if not state:
        await session.generate_reply(instructions=INTRO)


if __name__ == "__main__":
    cli.run_app(server)