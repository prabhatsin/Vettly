

from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli
from livekit.plugins import deepgram, google, silero

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
    await session.generate_reply(instructions="Greet the candidate and ask them to introduce themselves.")


if __name__ == "__main__":
    cli.run_app(server)