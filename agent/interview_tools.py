import logging
from typing import Literal

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from interview_state import InterviewState

logger = logging.getLogger("interview_tools")

MIN_NOTE_CHARS = 5
MAX_NOTE_CHARS = 400


class InterviewTools:
    """The interview logic behind the three tools. Returns text the LLM acts on."""

    def __init__(self, state: InterviewState, questions: list[dict]):
        self.state = state
        self.questions = questions

    async def next_question(self) -> str:
        idx = await self.state.begin_question()
        if idx == -1:
            return (
                "All questions have been asked. Thank the candidate, then call "
                "end_interview with reason 'completed'."
            )
        if idx == -2:
            raise ToolError("Interview state is unavailable. Continue the conversation naturally.")
        if idx == -3:
            raise ToolError("The interview has already ended. Say a brief goodbye only.")

        question = self.questions[idx]["question"]
        return (
            f"Question {idx + 1} of {len(self.questions)}: {question}\n"
            "Ask only this question, in your own natural spoken words, then stop and listen."
        )

    async def record_answer_note(self, note: str) -> str:
        note = (note or "").strip()
        if len(note) < MIN_NOTE_CHARS:
            raise ToolError(
                f"The note is too short. Write at least {MIN_NOTE_CHARS} characters "
                "describing what the candidate said."
            )
        if len(note) > MAX_NOTE_CHARS:
            raise ToolError(
                f"The note is too long. Keep it under {MAX_NOTE_CHARS} characters."
            )

        idx = await self.state.record_note(note)
        if idx == -1:
            return (
                "Nothing to record: the previous answer was already saved, or no question "
                "is open. Call next_question to continue."
            )
        if idx == -2:
            raise ToolError("Interview state is unavailable. Continue the conversation naturally.")
        if idx == -3:
            raise ToolError("The interview has already ended. Say a brief goodbye only.")

        remaining = len(self.questions) - (idx + 1)
        if remaining == 0:
            return (
                "Saved. That was the last question. Thank the candidate, then call "
                "end_interview with reason 'completed'."
            )
        return f"Saved. {remaining} questions left. Call next_question for the next one."

    async def end_interview(self, reason: str) -> str:
        snap = await self.state.snapshot()
        if snap is None:
            raise ToolError("Interview state is unavailable. Say a brief goodbye.")
        if snap.status == "ended":
            return "The interview is already ended. Just say a brief goodbye."

        if reason == "completed" and not snap.all_done:
            remaining = snap.total_questions - snap.current_index
            raise ToolError(
                f"{remaining} questions are not finished yet. If an answer is still unrecorded, "
                "call record_answer_note, then next_question. If the candidate asked to stop, "
                "call end_interview with reason 'candidate_request'."
            )

        await self.state.end()
        return (
            "The interview is closed. Say a short, warm goodbye and thank the candidate. "
            "Do not ask anything else."
        )


def build_tools(logic: InterviewTools) -> list:
    @function_tool()
    async def next_question(context: RunContext) -> str:
        """Get the next interview question to ask the candidate.

        Call this whenever you are ready to move to the next question, including right
        after the candidate's introduction. If you call it again before the answer is
        recorded, you get the same question back.
        """
        logger.info("tool: next_question")
        return await logic.next_question()

    @function_tool()
    async def record_answer_note(context: RunContext, note: str) -> str:
        """Save a short private note about the candidate's answer to the current question.

        Call this once you are finished with a question and its follow-up, before calling
        next_question.

        Args:
            note: One or two sentences on what the candidate said, strengths and gaps.
        """
        logger.info("tool: record_answer_note (%d chars)", len(note or ""))
        return await logic.record_answer_note(note)

    @function_tool()
    async def end_interview(
        context: RunContext, reason: Literal["completed", "candidate_request"]
    ) -> str:
        """Close the interview.

        Use 'completed' only after every question is asked and its note saved. Use
        'candidate_request' if the candidate clearly asks to stop.

        Args:
            reason: Either 'completed' or 'candidate_request'.
        """
        logger.info("tool: end_interview (%s)", reason)
        return await logic.end_interview(reason)

    return [next_question, record_answer_note, end_interview]