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


async def make(client, total=3):
    state = InterviewState(client, "app-1", total)
    await state.load_or_create()
    return InterviewTools(state, QUESTIONS[:total]), state


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

    assert "2 questions left" in result
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


async def test_record_twice_records_once(client):
    tools, state = await make(client)
    await tools.next_question()
    await tools.record_answer_note(NOTE)
    result = await tools.record_answer_note("A second note that should be ignored")

    assert "Nothing to record" in result
    assert await state.notes() == {0: NOTE}
    assert (await state.snapshot()).current_index == 1


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


async def test_build_tools_returns_three_tools(client):
    tools, _ = await make(client)
    assert len(build_tools(tools)) == 3