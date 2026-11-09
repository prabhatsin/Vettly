import logging
import os
from typing import Callable, Literal

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from interview_state import InterviewState

logger = logging.getLogger("interview_tools")

MIN_NOTE_CHARS = 5
MAX_NOTE_CHARS = 400
MAX_FOLLOWUPS = 1
LIMIT_SECONDS = int(os.getenv("INTERVIEW_LIMIT_SECONDS", 20 * 60))
WRAPUP_SECONDS = int(os.getenv("INTERVIEW_WRAPUP_SECONDS", 3 * 60))

UNAVAILABLE = "Interview state is unavailable. Continue the conversation naturally."
ENDED = "The interview has already ended. Say a brief goodbye only."
ALL_ASKED = (
    "All questions have been asked. Thank the candidate, then call "
    "end_interview with reason 'completed'."
)
LAST_QUESTION = (
    "Saved. That was the last question. Thank the candidate, then call "
    "end_interview with reason 'completed'."
)
WRAP_UP = (
    "Time is almost up, so do not ask any more questions. Thank the candidate, "
    "then call end_interview with reason 'time_limit'."
)


class InterviewTools:
    """The interview logic behind the tools. Returns text the LLM acts on."""

    def __init__(
        self,
        state: InterviewState,
        questions: list[dict],
        limit_seconds: float = LIMIT_SECONDS,
        wrapup_seconds: float = WRAPUP_SECONDS,
        max_followups: int = MAX_FOLLOWUPS,
        on_closed: Callable[[], None] | None = None,
    ):
        self.state = state
        self.questions = questions
        self.limit = limit_seconds
        self.wrapup_seconds = wrapup_seconds
        self.max_followups = max_followups
        self.on_closed = on_closed

    def _time_is_short(self, snap) -> bool:
        return snap.wrapup or snap.active_seconds >= self.limit - self.wrapup_seconds

    def _question_text(self, idx: int) -> str:
        return (
            f"Question {idx + 1} of {len(self.questions)}: {self.questions[idx]['question']}\n"
            "Ask only this question, in your own natural spoken words, then stop and listen."
        )

    async def _begin(self) -> str:
        idx = await self.state.begin_question()
        if idx == -1:
            return ALL_ASKED
        if idx == -2:
            raise ToolError(UNAVAILABLE)
        if idx == -3:
            raise ToolError(ENDED)
        return self._question_text(idx)

    async def next_question(self) -> str:
        snap = await self.state.snapshot()
        if (
            snap
            and snap.status == "active"
            and not snap.awaiting_answer
            and not snap.all_done
            and self._time_is_short(snap)
        ):
            return WRAP_UP
        return await self._begin()

    async def record_answer_note(self, note: str, question_number: int | None = None) -> str:
        note = (note or "").strip()
        if len(note) < MIN_NOTE_CHARS:
            raise ToolError(
                f"The note is too short. Write at least {MIN_NOTE_CHARS} characters "
                "describing what the candidate said."
            )
        if len(note) > MAX_NOTE_CHARS:
            raise ToolError(f"The note is too long. Keep it under {MAX_NOTE_CHARS} characters.")

        expected = None
        if question_number is not None:
            if not 1 <= question_number <= len(self.questions):
                raise ToolError(
                    f"question_number must be between 1 and {len(self.questions)}."
                )
            expected = question_number - 1

        idx = await self.state.record_note(note, expected)
        if idx == -1:
            snap = await self.state.snapshot()
            if snap and snap.awaiting_answer:
                return (
                    "Nothing to record: that answer was already saved. "
                    f"Question {snap.current_index + 1} is open. Continue with it, and use "
                    f"question_number {snap.current_index + 1} when you save its note."
                )
            return (
                "Nothing to record: the previous answer was already saved, or no question "
                "is open. Call next_question to continue."
            )
        if idx == -2:
            raise ToolError(UNAVAILABLE)
        if idx == -3:
            raise ToolError(ENDED)

        if len(self.questions) - (idx + 1) == 0:
            return LAST_QUESTION
        snap = await self.state.snapshot()
        if snap and self._time_is_short(snap):
            return "Saved. " + WRAP_UP
        return "Saved. " + await self._begin()

    async def request_followup(self, reason: str) -> str:
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise ToolError("Say what is missing from the answer, in at least 5 characters.")
        if len(reason) > 200:
            raise ToolError("Keep the reason under 200 characters.")

        snap = await self.state.snapshot()
        if snap and snap.status == "active" and self._time_is_short(snap):
            return "Time is short. Do not ask a follow-up. Save your note and move on."

        count = await self.state.try_followup(self.max_followups)
        if count == -1:
            return (
                "No more follow-ups are allowed for this question. Save your note with "
                "record_answer_note and move on."
            )
        if count == -2:
            raise ToolError(UNAVAILABLE)
        if count == -3:
            raise ToolError(ENDED)
        if count == -4:
            return "No question is open, so there is nothing to follow up on. Call next_question."
        return (
            f"Ask ONE brief follow-up about: {reason}. Then stop and listen. "
            "Do not ask another follow-up on this question."
        )

    async def repeat_question(self) -> str:
        snap = await self.state.snapshot()
        if snap is None:
            raise ToolError(UNAVAILABLE)
        if snap.status == "ended":
            raise ToolError(ENDED)
        if not snap.awaiting_answer:
            return "No question is open right now. Call next_question."
        idx = snap.current_index
        return (
            f"Repeat question {idx + 1} of {len(self.questions)}: "
            f"{self.questions[idx]['question']}\n"
            "Say it again, in slightly different words if that helps, then listen. "
            "This does not count as a follow-up."
        )

    async def skip_question(self) -> str:
        snap = await self.state.snapshot()
        if snap is None:
            raise ToolError(UNAVAILABLE)
        if snap.status == "ended":
            raise ToolError(ENDED)
        if not snap.awaiting_answer:
            return "No question is open, so there is nothing to skip. Call next_question."
        return await self.record_answer_note(
            "Candidate chose to skip this question.",
            question_number=snap.current_index + 1,
        )

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
                "call record_answer_note, which gives you the next question. If the candidate "
                "asked to stop, call end_interview with reason 'candidate_request'."
            )
        if reason == "time_limit" and not self._time_is_short(snap):
            raise ToolError("There is still enough time. Continue with the next question.")

        await self.state.end()
        if self.on_closed:
            self.on_closed()
        return (
            "The interview is closed. Say one short, warm goodbye and thank the candidate. "
            "Do not ask anything else."
        )


def build_tools(logic: InterviewTools) -> list:
    @function_tool()
    async def next_question(context: RunContext) -> str:
        """Get the next interview question to ask the candidate.

        Call this right after the candidate's introduction. After that, record_answer_note
        already gives you the next question. If you call this while a question is open,
        you get the same question back.
        """
        logger.info("tool: next_question")
        return await logic.next_question()

    @function_tool()
    async def record_answer_note(context: RunContext, question_number: int, note: str) -> str:
        """Save a short private note on the candidate's answer, then get the next question.

        Call this once you have a usable answer to the current question, after any follow-up.
        Only call it when the candidate has finished speaking.

        Args:
            question_number: The number of the question you are saving the note for, as in "Question 2 of 8".
            note: One or two sentences on what the candidate said, strengths and gaps.
        """
        logger.info("tool: record_answer_note q%s (%d chars)", question_number, len(note or ""))
        return await logic.record_answer_note(note, question_number)
 
    @function_tool()
    async def request_followup(context: RunContext, reason: str) -> str:
        """Ask permission for ONE follow-up when the answer is vague, hedging, very short
        or misses the point. Only ask the follow-up if this tool approves it.

        Args:
            reason: What is missing or unclear in the candidate's answer.
        """
        logger.info("tool: request_followup")
        return await logic.request_followup(reason)

    @function_tool()
    async def repeat_question(context: RunContext) -> str:
        """Get the current question again when the candidate asks you to repeat or
        rephrase it, or says they did not hear it."""
        logger.info("tool: repeat_question")
        return await logic.repeat_question()

    @function_tool()
    async def skip_question(context: RunContext) -> str:
        """Skip the current question when the candidate clearly says they want to skip it.
        It records the skip and gives you the next question."""
        logger.info("tool: skip_question")
        return await logic.skip_question()

    @function_tool()
    async def end_interview(
        context: RunContext,
        reason: Literal["completed", "candidate_request", "time_limit"],
    ) -> str:
        """Close the interview.

        Use 'completed' only after every question is asked and its note saved. Use
        'candidate_request' if the candidate clearly asks to stop. Use 'time_limit' only
        when the tools say time is almost up.

        Args:
            reason: 'completed', 'candidate_request' or 'time_limit'.
        """
        logger.info("tool: end_interview (%s)", reason)
        return await logic.end_interview(reason)

    return [
        next_question,
        record_answer_note,
        request_followup,
        repeat_question,
        skip_question,
        end_interview,
    ]