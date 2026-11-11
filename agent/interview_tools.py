import logging
import os
from typing import Any, Callable, Literal

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from interview_state import InterviewState
from session_data import STAGES
import time

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
FOLLOWUP_PENDING = (
    "A follow-up is pending. Wait for the candidate's answer before saving the note."
)
STAGE_DONE = (
    "[internal, not from the candidate] This stage's questions are finished. Do not speak "
    "to the candidate. Call stage_done now with a 2-3 sentence summary of what you "
    "learned in this stage."
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
        stage: str = "screener",
        stage_end: int | None = None,
        min_skip_gap: float = 6.0,
        stage_start: int = 0,
        on_stage_complete: Callable[[str, str], Any] | None = None,
        on_interview_complete: Callable[[], None] | None = None,
        turn_guard: bool = False,
    ):
        self.state = state
        self.questions = questions
        self.limit = limit_seconds
        self.wrapup_seconds = wrapup_seconds
        self.max_followups = max_followups
        self.on_closed = on_closed
        self.stage = stage
        self.stage_end = stage_end if stage_end is not None else len(questions)
        self.min_skip_gap = min_skip_gap
        self._issued_at = float("-inf")
        # Last skip or skip-like command; interviewer.py drops leftover STT words after it.
        self.last_command_at = float("-inf")
        # Set by the agent: the code does the stage handoff / interview end itself.
        self.stage_start = stage_start
        self.on_stage_complete = on_stage_complete
        self.on_interview_complete = on_interview_complete
        self._handed_off = False
        self._ended = False
        # Turn guard: only on when the agent reports committed user turns (on_user_turn).
        self.turn_guard = turn_guard
        self.followup_pending = False
        self.user_spoke_since_question = False

    def _blocked(self, tool: str, question: int | str, why: str) -> None:
        logger.info("guard: blocked %s on q%s: %s", tool, question, why)

    def on_user_turn(self) -> None:
        """A candidate turn was committed: they answered the question or the follow-up."""
        self.user_spoke_since_question = True
        self.followup_pending = False

    def _time_is_short(self, snap) -> bool:
        return snap.wrapup or snap.active_seconds >= self.limit - self.wrapup_seconds

    def _question_text(self, idx: int) -> str:
        return (
            f"Question {idx + 1} of {len(self.questions)}: {self.questions[idx]['question']}\n"
            f"When you save its note, use question_number {idx + 1}.\n"
            "Ask only this question, in your own natural spoken words, in ONE short reply, "
            "then stop and listen. Do not call any other tool until the candidate answers."
        )

    async def _begin(self) -> str:
        snap = await self.state.snapshot()
        if (
            snap
            and snap.status == "active"
            and not snap.awaiting_answer
            and not snap.all_done
            and snap.current_index >= self.stage_end
        ):
            return STAGE_DONE

        idx = await self.state.begin_question()
        if idx == -1:
            return ALL_ASKED
        if idx == -2:
            raise ToolError(UNAVAILABLE)
        if idx == -3:
            raise ToolError(ENDED)

        self._issued_at = time.monotonic()
        self.user_spoke_since_question = False
        self.followup_pending = False
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

    async def record_answer_note(
        self, note: str, question_number: int | None = None, *, tool: str = "record_answer_note"
    ) -> Any:
        note = (note or "").strip()
        if len(note) < MIN_NOTE_CHARS:
            raise ToolError(
                f"The note is too short. Write at least {MIN_NOTE_CHARS} characters "
                "describing what the candidate said."
            )
        if len(note) > MAX_NOTE_CHARS:
            logger.warning("note too long (%d chars); truncating to %d", len(note), MAX_NOTE_CHARS)
            note = note[:MAX_NOTE_CHARS]

        expected = None
        if question_number is not None:
            if not 1 <= question_number <= len(self.questions):
                raise ToolError(
                    f"question_number must be between 1 and {len(self.questions)}."
                )
            expected = question_number - 1

        if self.turn_guard:
            refusal = await self._note_refusal(question_number, tool)
            if refusal:
                return refusal

        idx = await self.state.record_note(note, expected)
        if idx == -1:
            self._blocked(tool, question_number, "nothing to record (no open question or wrong number)")
            snap = await self.state.snapshot()
            if snap and snap.awaiting_answer:
                open_no = snap.current_index + 1
                if question_number is not None and question_number != open_no - 1:
                    return (
                        "Nothing to record: wrong question_number. Question "
                        f"{open_no} is the open one. Save a note for it only after the "
                        "candidate has answered it."
                    )
                return (
                    "Nothing to record: that answer was already saved. "
                    f"Question {open_no} is open. Continue with it, and use "
                    f"question_number {open_no} when you save its note."
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
            if self.on_interview_complete:
                return await self._auto_end()
            return LAST_QUESTION
        snap = await self.state.snapshot()
        if snap and self._time_is_short(snap):
            return "Saved. " + WRAP_UP
        if self.on_stage_complete and idx + 1 >= self.stage_end and self.stage != STAGES[-1]:
            return await self._auto_handoff()
        return "Saved. " + await self._begin()

    async def _note_refusal(self, question_number: int | None, tool: str) -> str | None:
        """Why a note can't be saved yet, or None if it can."""
        snap = await self.state.snapshot()
        if not snap or not snap.awaiting_answer:
            return None  # record_note reports these cases itself
        open_no = snap.current_index + 1
        if self.followup_pending:
            self._blocked(tool, open_no, "follow-up pending")
            return FOLLOWUP_PENDING
        if question_number is not None and question_number != open_no:
            self._blocked(tool, open_no, f"wrong question_number {question_number}")
            return (
                f"Question {open_no} is the open question, not {question_number}. "
                f"Wait for the candidate's answer to question {open_no}."
            )
        if not self.user_spoke_since_question:
            self._blocked(tool, open_no, "candidate has not spoken since the question")
            return f"The candidate hasn't answered question {open_no} yet. Wait and listen."
        if snap.current_index in await self.state.notes():
            self._blocked(tool, open_no, "question already has a note")
            return f"Question {open_no} already has a note. Do not save another one."
        return None

    async def _auto_end(self) -> None:
        """Last note saved: end the interview in code. Returns None so the LLM says nothing."""
        if self._ended:
            return None
        self._ended = True
        await self.state.end()
        logger.info("auto end: last question saved")
        self.on_interview_complete()
        if self.on_closed:
            self.on_closed()
        return None

    async def _auto_handoff(self) -> Any:
        """Last note of this stage saved: hand off in code, with a summary built from the notes.
        Returns the next agent (or None if already handed off)."""
        if self._handed_off:
            return None
        notes = await self.state.notes()
        lines = [
            f"Q{i + 1}: {n}" for i, n in notes.items() if self.stage_start <= i < self.stage_end
        ]
        summary = (" ".join(lines) or f"The {self.stage} stage was completed.")[:600]
        try:
            nxt, advanced = await self.complete_stage(summary)
        except ToolError:
            logger.exception("auto handoff failed; falling back to stage_done")
            return "Saved. " + await self._begin()
        self._handed_off = True
        if not advanced:
            return None
        logger.info("auto handoff: %s -> %s", self.stage, nxt)
        return self.on_stage_complete(nxt, summary)

    async def request_followup(self, reason: str) -> str:
        # Forgiving: never reject on length, just clean it up.
        reason = (reason or "").strip() or "the answer needs more detail"
        reason = reason[:200]

        snap = await self.state.snapshot()
        if snap and snap.status == "active" and self._time_is_short(snap):
            self._blocked("request_followup", snap.current_index + 1, "time is short")
            return "Time is short. Do not ask a follow-up. Save your note and move on."

        count = await self.state.try_followup(self.max_followups)
        if count == -1:
            self._blocked("request_followup", snap.current_index + 1 if snap else "?", "follow-up limit reached")
            return (
                "Follow-up limit reached. No more follow-ups for this question. "
                "Save the note with record_answer_note."
            )
        if count == -2:
            raise ToolError(UNAVAILABLE)
        if count == -3:
            raise ToolError(ENDED)
        if count == -4:
            return "No question is open, so there is nothing to follow up on. Call next_question."
        self.followup_pending = True
        return (
            f"Ask ONE brief follow-up about: {reason}. Ask the follow-up now in one short "
            "sentence, then stop and listen. Do not call any other tool."
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
        if self.turn_guard and self.followup_pending:
            self._blocked("skip_question", snap.current_index + 1, "follow-up pending")
            return FOLLOWUP_PENDING
        if time.monotonic() - self._issued_at < self.min_skip_gap:
            self._blocked("skip_question", snap.current_index + 1, "question was issued too recently")
            return (
                "You have not asked this question yet. Ask it first. Skip it only if "
                "the candidate asks to skip after hearing it."
            )
        self.last_command_at = time.monotonic()
        return await self.record_answer_note(
            "Candidate chose to skip this question.",
            question_number=snap.current_index + 1,
            tool="skip_question",
        )

    async def complete_stage(self, summary: str) -> tuple[str, bool]:
        """Move to the next stage. Returns (stage_name, advanced).
        advanced is False when the stage had already moved on (a repeated call).
        """
        summary = (summary or "").strip()
        if len(summary) < 10:
            raise ToolError("Write a stage summary of at least 10 characters.")

        snap = await self.state.snapshot()
        if snap is None:
            raise ToolError(UNAVAILABLE)
        if snap.status == "ended":
            raise ToolError(ENDED)

        current = await self.state.get_stage()
        if current != self.stage:
            return current, False
        if self.stage == STAGES[-1]:
            raise ToolError("This is the last stage. Use end_interview when done.")
        if snap.awaiting_answer or snap.current_index < self.stage_end:
            raise ToolError("This stage is not finished. Save the open answer note first.")

        nxt = STAGES[STAGES.index(self.stage) + 1]
        await self.state.save_summary(self.stage, summary[:600])
        await self.state.set_stage(nxt)
        return nxt, True

    async def end_interview(self, reason: str, summary: str = "") -> str:
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

        if summary.strip():
            await self.state.save_summary(self.stage, summary.strip()[:600])
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
    async def record_answer_note(
        context: RunContext,
        question_number: int,
        note: str = "",
        question_note: str = "",
    ):
        """Save a short private note on the candidate's answer, then get the next question.

        Call this once you have a usable answer to the current question, after any follow-up.
        Only call it when the candidate has finished speaking. If the candidate says they
        don't know or can't answer, call this with a note saying they did not know.

        Args:
            question_number: The number of the question you are saving the note for, as in "Question 2 of 8".
            note: One or two sentences on what the candidate said, strengths and gaps.
            question_note: Same as note; use note.
        """
        text = note or question_note
        logger.info("tool: record_answer_note q%s (%d chars)", question_number, len(text or ""))
        return await logic.record_answer_note(text, question_number)

    @function_tool()
    async def request_followup(context: RunContext, reason: str = "") -> str:
        """Ask permission for ONE follow-up when the answer is vague, hedging, very short
        or misses the point. Only ask the follow-up if this tool approves it.
        Never call this when the candidate says they don't know or can't answer.

        Args:
            reason: What is missing or unclear in the candidate's answer (one short sentence).
        """
        logger.info("tool: request_followup")
        return await logic.request_followup(reason)

    @function_tool()
    async def repeat_question(context: RunContext) -> str:
        """Get the current question again ONLY when the candidate explicitly asks you to
        repeat or rephrase it, or says they did not hear it. Never for unclear single
        words or speech-recognition noise."""
        logger.info("tool: repeat_question")
        return await logic.repeat_question()

    @function_tool()
    async def skip_question(context: RunContext):
        """Skip the current question. Call this when the candidate says skip, next, next
        question, move on, pass, or clearly says they don't know or can't answer.
        Never for "okay", "yes", or silence.
        It records the skip and gives you the next question."""
        logger.info("tool: skip_question")
        return await logic.skip_question()

    @function_tool()
    async def end_interview(
        context: RunContext,
        reason: Literal["completed", "candidate_request", "time_limit"],
        stage_summary: str = "",
    ) -> str:
        """Close the interview.

        Use 'completed' only after every question is asked and its note saved. Use
        'candidate_request' if the candidate clearly asks to stop. Use 'time_limit' only
        when the tools say time is almost up.

        Args:
            reason: 'completed', 'candidate_request' or 'time_limit'.
            stage_summary: 2-3 sentences summarising what you learned in your stage.
        """
        logger.info("tool: end_interview (%s)", reason)
        return await logic.end_interview(reason, stage_summary)

    return [
        next_question,
        record_answer_note,
        request_followup,
        repeat_question,
        skip_question,
        end_interview,
    ]