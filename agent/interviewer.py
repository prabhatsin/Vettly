
from pathlib import Path
from dotenv import load_dotenv
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli
from livekit.plugins import deepgram, google, silero
import logging
import os
import uuid
import aiohttp

logger = logging.getLogger("interviewer")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

server = AgentServer()


class Interviewer(Agent):
    def __init__(self):
        super().__init__(
            instructions=(
                "You are Iris, a friendly AI interviewer. Keep replies short, "
                "one or two sentences. Greet the candidate and ask them to "
                "introduce themselves."
            )
        )

@server.rtc_session()
async def entrypoint(ctx: JobContext):
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=google.LLM(model="gemini-3.5-flash"),
        tts=deepgram.TTS(model="aura-2-thalia-en"),
        vad=silero.VAD.load(),
    )
    await session.start(agent=Interviewer(), room=ctx.room)
    room_name = ctx.room.name
    try:
        application_id = uuid.UUID(room_name.removeprefix("interview-"))
    except ValueError:
        application_id = None

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
    await session.generate_reply(instructions="Greet the candidate and ask them to introduce themselves.")


if __name__ == "__main__":
    cli.run_app(server)