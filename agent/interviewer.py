
from pathlib import Path
from dotenv import load_dotenv
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli
from livekit.plugins import deepgram, google, silero
import logging
import os
import uuid
import aiohttp
from plan_client import application_id_from_room, fetch_plan
from prompts import build_instructions

logger = logging.getLogger("interviewer")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

server = AgentServer()


class Interviewer(Agent):
    def __init__(self, instructions: str):
        super().__init__(instructions=instructions)

@server.rtc_session()
async def entrypoint(ctx: JobContext):

    application_id = application_id_from_room(ctx.job.room.name)
    plan = await fetch_plan(application_id) if application_id else None
    logger.info(
        "plan loaded: %s questions",
        len(plan["questions"]) if plan else "no",
    )
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=google.LLM(model="gemini-3.5-flash"),
        tts=deepgram.TTS(model="aura-2-thalia-en"),
        vad=silero.VAD.load(),
    )
    await session.start(agent=Interviewer(build_instructions(plan)), room=ctx.room)


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
    await session.generate_reply(instructions="Greet the candidate in one short sentence and ask them to briefly introduce themselves.")


if __name__ == "__main__":
    cli.run_app(server)