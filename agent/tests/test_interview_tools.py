import fakeredis.aioredis
import pytest
from livekit.agents.llm import ToolError

from interview_state import InterviewState
from interview_tools import InterviewTools, build_tools

QUESTIONS = [
    {"category": "technical_depth", "question": f"Plan question number {i + 1}", "why": "test"}
    for i in range(3)
]
NOTE = "Candidate explained the approach clearly"


@pytest.fixture()
async def client():
    c = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield c
    await c.aclose()


async def make(client, total=3, on_closed=None):
    state = InterviewState(client, "app-1", total)
    await state.load_or_create()
    return InterviewTools(state, QUESTIONS[:total], on_closed=on_closed), state


async def test_next_question_returns_first_question(client):
    tools, _ = await make(client)
    text = await tools.next_question()
    assert "Plan question number 1" in text
    assert "Question 1 of 3" in text


async def test_next_question_twice_returns_same_question(client):
    tools, _ = await make(client)
    first = await tools.next_question()
    second = await tools.next_question()
    assert first == second


async def test_record_note_advances_to_next_question(client):
    tools, state = await make(client)
    await tools.next_question()
    result = await tools.record_answer_note(NOTE)

    assert "Plan question number 2" in result  # CHANGED: the result now carries the next question
    assert (await state.notes()) == {0: NOTE}
    assert "Plan question number 2" in await tools.next_question()


async def test_short_note_rejected_and_state_unchanged(client):
    tools, state = await make(client)
    await tools.next_question()

    with pytest.raises(ToolError) as exc:
        await tools.record_answer_note("ok")
    assert "too short" in exc.value.message

    snap = await state.snapshot()
    assert snap.awaiting_answer is True
    assert snap.current_index == 0
    assert await state.notes() == {}


async def test_long_note_rejected(client):
    tools, _ = await make(client)
    await tools.next_question()
    with pytest.raises(ToolError) as exc:
        await tools.record_answer_note("x" * 401)
    assert "too long" in exc.value.message


async def test_empty_note_rejected(client):
    tools, _ = await make(client)
    await tools.next_question()
    with pytest.raises(ToolError):
        await tools.record_answer_note("   ")


async def test_record_twice_records_once(client):  # CHANGED: uses question_number
    tools, state = await make(client)
    await tools.next_question()
    await tools.record_answer_note(NOTE, question_number=1)
    result = await tools.record_answer_note(
        "A second note that should be ignored", question_number=1
    )

    assert "Nothing to record" in result
    assert await state.notes() == {0: NOTE}
    snap = await state.snapshot()
    assert snap.current_index == 1
    assert snap.awaiting_answer is True


async def test_wrong_question_number_records_nothing(client):  # NEW
    tools, state = await make(client)
    await tools.next_question()
    result = await tools.record_answer_note(NOTE, question_number=2)

    assert "Nothing to record" in result
    assert await state.notes() == {}
    assert (await state.snapshot()).current_index == 0


async def test_question_number_out_of_range_rejected(client):  # NEW
    tools, _ = await make(client)
    await tools.next_question()
    for bad in (0, 4):
        with pytest.raises(ToolError):
            await tools.record_answer_note(NOTE, question_number=bad)


async def test_record_without_question_is_noop(client):
    tools, state = await make(client)
    result = await tools.record_answer_note(NOTE)
    assert "Nothing to record" in result
    assert await state.notes() == {}
    assert (await state.snapshot()).current_index == 0


async def test_last_note_points_to_end_then_next_reports_done(client):
    tools, _ = await make(client, total=1)
    await tools.next_question()
    result = await tools.record_answer_note(NOTE)
    assert "last question" in result
    assert "end_interview" in result

    assert "All questions have been asked" in await tools.next_question()


async def test_end_completed_refused_while_questions_remain(client):
    tools, state = await make(client)
    with pytest.raises(ToolError) as exc:
        await tools.end_interview("completed")
    assert "not finished" in exc.value.message
    assert (await state.snapshot()).status == "active"


async def test_end_completed_refused_when_last_answer_unrecorded(client):
    tools, _ = await make(client, total=1)
    await tools.next_question()
    with pytest.raises(ToolError):
        await tools.end_interview("completed")


async def test_end_completed_after_all_done_then_idempotent(client):
    tools, state = await make(client, total=1)
    await tools.next_question()
    await tools.record_answer_note(NOTE)

    assert "closed" in await tools.end_interview("completed")
    assert (await state.snapshot()).status == "ended"
    assert "already ended" in await tools.end_interview("completed")


async def test_end_candidate_request_midway(client):
    tools, state = await make(client)
    await tools.next_question()
    await tools.end_interview("candidate_request")
    assert (await state.snapshot()).status == "ended"


async def test_tools_refuse_after_end(client):
    tools, _ = await make(client)
    await tools.end_interview("candidate_request")

    with pytest.raises(ToolError) as exc:
        await tools.next_question()
    assert "already ended" in exc.value.message

    with pytest.raises(ToolError):
        await tools.record_answer_note(NOTE)


async def test_missing_state_gives_tool_error(client):
    tools, state = await make(client)
    await client.delete(state.key)

    with pytest.raises(ToolError) as exc:
        await tools.next_question()
    assert "unavailable" in exc.value.message


async def test_full_flow_follows_plan_order(client):
    tools, state = await make(client)

    for i in range(3):
        text = await tools.next_question()
        assert f"Plan question number {i + 1}" in text
        assert f"Question {i + 1} of 3" in text
        await tools.record_answer_note(f"Note for question {i + 1} here")

    assert await state.notes() == {
        0: "Note for question 1 here",
        1: "Note for question 2 here",
        2: "Note for question 3 here",
    }
    assert "closed" in await tools.end_interview("completed")


async def test_build_tools_returns_six_tools(client):  # CHANGED: renamed, 3 -> 6
    tools, _ = await make(client)
    assert len(build_tools(tools)) == 6


async def test_record_note_returns_next_question_in_same_result(client):
    tools, state = await make(client)
    await tools.next_question()
    result = await tools.record_answer_note(NOTE)
    assert "Plan question number 2" in result
    assert (await state.snapshot()).awaiting_answer is True


async def test_followup_allowed_once_then_refused(client):
    tools, _ = await make(client)
    await tools.next_question()
    assert "ONE brief follow-up" in await tools.request_followup("No detail on key storage")
    assert "No more follow-ups" in await tools.request_followup("Still vague about it")


async def test_followup_allowed_again_on_next_question(client):
    tools, _ = await make(client)
    await tools.next_question()
    await tools.request_followup("No detail on key storage")
    await tools.record_answer_note(NOTE)
    assert "ONE brief follow-up" in await tools.request_followup("Missing the trade-offs")


async def test_followup_without_open_question(client):
    tools, _ = await make(client)
    assert "No question is open" in await tools.request_followup("Nothing to follow up on")


async def test_followup_reason_validated(client):
    tools, _ = await make(client)
    await tools.next_question()
    with pytest.raises(ToolError):
        await tools.request_followup("no")


async def test_followup_refused_when_time_short(client):
    tools, state = await make(client)
    await tools.next_question()
    await client.hset(state.key, "active_seconds", 1100)
    assert "Time is short" in await tools.request_followup("Missing the trade-offs")


async def test_next_question_wraps_up_when_time_short(client):
    tools, state = await make(client)
    await client.hset(state.key, "active_seconds", 1100)
    text = await tools.next_question()
    assert "time_limit" in text
    assert (await state.snapshot()).awaiting_answer is False


async def test_record_note_wraps_up_when_time_short(client):
    tools, state = await make(client)
    await tools.next_question()
    await client.hset(state.key, "wrapup", 1)
    result = await tools.record_answer_note(NOTE)
    assert "Saved." in result and "time_limit" in result
    assert await state.notes() == {0: NOTE}


async def test_end_time_limit_refused_when_plenty_of_time(client):
    tools, _ = await make(client)
    with pytest.raises(ToolError) as exc:
        await tools.end_interview("time_limit")
    assert "enough time" in exc.value.message


async def test_end_time_limit_allowed_when_short(client):
    tools, state = await make(client)
    await client.hset(state.key, "active_seconds", 1100)
    await tools.end_interview("time_limit")
    assert (await state.snapshot()).status == "ended"


async def test_repeat_question_returns_current_question(client):
    tools, _ = await make(client)
    await tools.next_question()
    text = await tools.repeat_question()
    assert "Plan question number 1" in text
    assert "does not count as a follow-up" in text


async def test_repeat_without_open_question(client):
    tools, _ = await make(client)
    assert "No question is open" in await tools.repeat_question()


async def test_skip_records_note_and_gives_next_question(client):
    tools, state = await make(client)
    await tools.next_question()
    result = await tools.skip_question()
    assert "Plan question number 2" in result
    assert await state.notes() == {0: "Candidate chose to skip this question."}


async def test_skip_without_open_question(client):
    tools, state = await make(client)
    assert "nothing to skip" in await tools.skip_question()
    assert await state.notes() == {}


async def test_on_closed_called_once_per_interview(client):
    calls = []
    tools, _ = await make(client, on_closed=lambda: calls.append(1))
    await tools.end_interview("candidate_request")
    await tools.end_interview("candidate_request")
    assert calls == [1]