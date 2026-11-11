import asyncio
import logging
import os
import re
import time
from pathlib import Path
import aiohttp
import redis.asyncio as aioredis
from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    StopResponse,
    TurnHandlingOptions,
    cli,
    function_tool,
)
from livekit.agents.llm import ToolError
from livekit.agents.tts import FallbackAdapter
from livekit.agents.voice import text_transforms
from livekit.plugins import silero,cerebras
from livekit.plugins import gnani

from interview_state import InterviewState
from interview_timer import close_when_quiet, run_timer
from interview_tools import LIMIT_SECONDS, WRAPUP_SECONDS, InterviewTools, build_tools
from plan_client import application_id_from_room, fetch_plan
from prompts import STAGE_NOTES, build_instructions
from session_data import STAGES, SessionData, split_ranges

logger = logging.getLogger("interviewer")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")



def prewarm(proc: JobProcess):
    """Runs once per worker process, before any job: load the VAD and warm slow imports."""
    proc.userdata["vad"] = silero.VAD.load()
    import openai  # noqa: F401  (used by the cerebras plugin)
    import websockets  # noqa: F401  (used by the gnani websocket TTS)


server = AgentServer(setup_fnc=prewarm, num_idle_processes=1)

INTRO_TEXT = "Hello and welcome! Could you please briefly introduce yourself?"
CONTINUE_LEAD = "Ask this question now. No greeting, no transition, no commentary."
REJOIN_LEAD = "Say 'welcome back' in a few words, then ask this question. No other commentary."
GOODBYE_TEXT = (
    "That was the last question. Thank you for your time today. "
    "The hiring team will review the interview and be in touch. Goodbye."
)

# Single words STT often leaves behind after a skip command ("next ... question").
LEFTOVER_WORDS = {"question", "next", "yes", "yeah", "skip", "okay", "ok", "ahead"}
COMMAND_RE = re.compile(r"\b(skip|next|move on|move ahead|go ahead|pass)\b", re.IGNORECASE)
# A turn ending with one of these is skipped in code, so the LLM can't follow up instead.
SKIP_END_RE = re.compile(
    r"\b(next question|next|skip the question|skip|move on)[\s.,!?]*$", re.IGNORECASE
)
# Shorter than InterviewTools.min_skip_gap (6s): a real skip that soon is refused anyway.
LEFTOVER_WINDOW = 5.0

# Filler Iris must not say after a question; dropped from TTS if the model says it anyway.
FILLER_PHRASES = [
    "I'll wait for your answer.", "I'll wait for your answer",
    "I’ll wait for your answer.", "I’ll wait for your answer",
    "I will wait for your answer.", "I will wait for your answer",
    "I'll wait for your response.", "I'll wait for your response",
    "Take your time.", "Take your time",
    "Whenever you're ready.", "Whenever you're ready",
    "Go ahead.",
]
drop_filler = text_transforms.replace({p: "" for p in FILLER_PHRASES})


async def drop_tool_text(text):
    """TTS text transform: drop anything inside [...] or {...}, e.g. a tool call the
    model typed as text ("[assistant called: end_interview with {...}]") or a JSON blob."""
    depth = 0
    async for chunk in text:
        out = []
        for ch in chunk:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth = max(0, depth - 1)
            elif depth == 0:
                out.append(ch)
        if out:
            yield "".join(out)


class Interviewer(Agent):
    """Single-agent fallback used when Redis state is unavailable."""

    def __init__(self, instructions: str, tools: list | None = None):
        super().__init__(instructions=instructions, tools=tools or [])


class StageAgent(Agent):
    stage = "screener"

    def __init__(self, data: SessionData, rejoin: bool = False):
        self.data = data
        self.rejoin = rejoin
        start, end = data.ranges[self.stage]
        self.logic = InterviewTools(
            data.state, data.plan["questions"],
            stage=self.stage, stage_end=end, on_closed=data.on_closed,
            stage_start=start,
            on_stage_complete=lambda nxt, summary: next_agent(self.logic, data, nxt, summary),
            on_interview_complete=lambda: self.session.say(GOODBYE_TEXT, allow_interruptions=False),
            turn_guard=True,
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

    async def on_user_turn_completed(self, turn_ctx, new_message):
        # Runs for each committed candidate turn, before the LLM replies.
        text = (new_message.text_content or "").strip()
        if not text or text.startswith("[continue]"):
            return
        now = time.monotonic()
        word = text.lower().strip(" .,!?")
        since = now - self.logic.last_command_at
        if word in LEFTOVER_WORDS and since < LEFTOVER_WINDOW:
            # Leftover tail of a skip command: no reply, keep listening.
            logger.info("guard: dropped leftover STT word %r (%.1fs after a command)", word, since)
            raise StopResponse()
        if COMMAND_RE.search(text):
            self.logic.last_command_at = now
        self.logic.on_user_turn()
        if SKIP_END_RE.search(text) and await self._skip_in_code():
            raise StopResponse()

    async def _skip_in_code(self) -> bool:
        """Run skip_question's logic directly. Returns False if the skip was refused,
        so the turn goes to the LLM as usual."""
        try:
            before = await self.logic.state.snapshot()
            result = await self.logic.skip_question()
            after = await self.logic.state.snapshot()
        except ToolError as e:
            logger.info("code skip not done: %s", e.message)
            return False
        if not before or not after or (
            after.current_index == before.current_index and after.status == before.status
        ):
            logger.info("code skip refused: %s", result if isinstance(result, str) else result)
            return False
        logger.info("code skip: q%d skipped", before.current_index + 1)
        if isinstance(result, Agent):
            self.session.update_agent(result)  # stage handoff; next agent asks its question
        elif isinstance(result, str):
            lead = f"{CONTINUE_LEAD}\n\n" if "Question " in result else ""
            self.session.generate_reply(user_input=f"[continue] {lead}{result}")
        # None: the interview ended and the goodbye is already playing.
        return True

    async def on_enter(self):
        if self.stage == "screener" and not self.rejoin:
            await self.session.say(INTRO_TEXT)
            return
        lead = REJOIN_LEAD if self.rejoin else CONTINUE_LEAD
        try:
            first = await self.logic.next_question()
        except Exception:
            first = "Continue the interview."
        await self.session.generate_reply(user_input=f"[continue] {lead}\n\n{first}")


class ScreenerAgent(StageAgent):
    stage = "screener"


class TechnicalAgent(StageAgent):
    stage = "technical"


class BehavioralAgent(StageAgent):
    stage = "behavioral"


AGENTS = {"screener": ScreenerAgent, "technical": TechnicalAgent, "behavioral": BehavioralAgent}


def next_agent(logic: InterviewTools, data: SessionData, nxt: str, summary: str) -> Agent:
    """Record the stage summary and build the next stage's agent (handoff target)."""
    data.summaries[logic.stage] = summary.strip()[:600]
    data.stage = nxt
    logger.info("handoff: %s -> %s", logic.stage, nxt)
    agent = AGENTS[nxt](data)
    agent.logic.last_command_at = logic.last_command_at  # a skip can trigger the handoff
    return agent


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
        logic._handed_off = True
        return next_agent(logic, data, nxt, summary), "Done. Output nothing."

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
        llm=cerebras.LLM(model="qwen-3.8-27b", parallel_tool_calls=False),
        tts=FallbackAdapter(
            [
                gnani.TTS(model="timbre-v2.5",voice="Kaveri",language="en-IN",synthesize_method="websocket"),
                gnani.TTS(model="timbre-v3.0",voice="Shivani",language="en-IN",synthesize_method="websocket"),
            ],
            max_retry_per_tts=1,
        ),
        tts_text_transforms=[drop_tool_text, drop_filler, "filter_markdown", "filter_emoji"],
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(
            endpointing={"mode": "fixed", "min_delay": 1.3, "max_delay": 2.5},
            interruption={
                "min_words": 2,
                "min_duration": 0.6,
                "resume_false_interruption": True,
                "false_interruption_timeout": 1.5,
            },
            preemptive_generation={"enabled": False},
        ),
        userdata=data,
    )
    logger.info("LLM in use: %s", type(session.llm).__name__)
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
            if text.startswith("[continue]"):
                continue
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
        await session.say(INTRO_TEXT)


if __name__ == "__main__":
    cli.run_app(server)