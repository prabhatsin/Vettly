import asyncio

import fakeredis.aioredis
import pytest

from interview_state import InterviewState


@pytest.fixture()
async def client():
    c = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield c
    await c.aclose()


def make(client, total=3, app_id="app-1"):
    return InterviewState(client, app_id, total)


async def test_create_sets_initial_values(client):
    snap = await make(client).load_or_create()
    assert snap.current_index == 0
    assert snap.followups_used == 0
    assert snap.total_questions == 3
    assert snap.status == "active"
    assert snap.all_done is False


async def test_load_or_create_twice_does_not_reset(client):
    state = make(client)
    await state.load_or_create()
    await state.advance()
    await state.add_followup()

    snap = await make(client).load_or_create()
    assert snap.current_index == 1
    assert snap.followups_used == 1


async def test_advance_moves_forward_and_resets_followups(client):
    state = make(client)
    await state.load_or_create()
    await state.add_followup()
    snap = await state.advance()
    assert snap.current_index == 1
    assert snap.followups_used == 0


async def test_advance_stops_at_total(client):
    state = make(client, total=2)
    await state.load_or_create()
    for _ in range(5):
        snap = await state.advance()
    assert snap.current_index == 2
    assert snap.all_done is True


async def test_add_followup_counts(client):
    state = make(client)
    await state.load_or_create()
    assert await state.add_followup() == 1
    assert await state.add_followup() == 2


async def test_end_is_idempotent(client):
    state = make(client)
    await state.load_or_create()
    await state.end()
    await state.end()
    assert (await state.snapshot()).status == "ended"


async def test_elapsed_grows_from_stored_start(client):
    state = make(client)
    await state.load_or_create()
    await client.hset(state.key, "started_at", 1000.0)
    snap = await state.snapshot()
    assert snap.elapsed_seconds > 1_000_000


async def test_second_object_sees_first_objects_state(client):
    first = make(client)
    await first.load_or_create()
    await first.advance()

    restarted = make(client)
    snap = await restarted.snapshot()
    assert snap.current_index == 1


async def test_concurrent_advances_respect_bound(client):
    state = make(client, total=3)
    await state.load_or_create()
    await state.advance()
    await state.advance()

    await asyncio.gather(state.advance(), state.advance())
    assert (await state.snapshot()).current_index == 3


async def test_snapshot_missing_returns_none(client):
    assert await make(client, app_id="nobody").snapshot() is None


async def test_begin_question_is_idempotent(client):
    state = make(client)
    await state.load_or_create()
    assert await state.begin_question() == 0
    assert await state.begin_question() == 0
    assert (await state.snapshot()).awaiting_answer is True


async def test_record_note_stores_advances_and_clears_flag(client):
    state = make(client)
    await state.load_or_create()
    await state.begin_question()
    assert await state.record_note("solid on asyncio") == 0

    snap = await state.snapshot()
    assert snap.current_index == 1
    assert snap.awaiting_answer is False
    assert await state.notes() == {0: "solid on asyncio"}
    assert await state.begin_question() == 1


async def test_record_note_twice_records_once(client):
    state = make(client)
    await state.load_or_create()
    await state.begin_question()
    await state.record_note("first note")
    assert await state.record_note("second note") == -1

    assert await state.notes() == {0: "first note"}
    assert (await state.snapshot()).current_index == 1


async def test_record_note_without_question_asked_does_nothing(client):
    state = make(client)
    await state.load_or_create()
    assert await state.record_note("orphan") == -1
    assert (await state.snapshot()).current_index == 0
    assert await state.notes() == {}


async def test_begin_after_last_question_reports_done(client):
    state = make(client, total=1)
    await state.load_or_create()
    await state.begin_question()
    await state.record_note("only one")
    assert await state.begin_question() == -1


async def test_tools_refuse_after_end(client):
    state = make(client)
    await state.load_or_create()
    await state.end()
    assert await state.begin_question() == -3
    assert await state.record_note("late") == -3


async def test_missing_state_returns_minus_two(client):
    state = make(client, app_id="nobody")
    assert await state.begin_question() == -2
    assert await state.record_note("x") == -2

async def test_try_followup_respects_cap(client):
    state = make(client)
    await state.load_or_create()
    await state.begin_question()
    assert await state.try_followup(1) == 1
    assert await state.try_followup(1) == -1


async def test_try_followup_without_open_question(client):
    state = make(client)
    await state.load_or_create()
    assert await state.try_followup(1) == -4


async def test_followup_count_resets_after_note(client):
    state = make(client)
    await state.load_or_create()
    await state.begin_question()
    await state.try_followup(1)
    await state.record_note("first answer note")
    await state.begin_question()
    assert await state.try_followup(1) == 1


async def test_tick_accumulates_connected_time(client):
    state = make(client)
    await state.load_or_create()
    assert await state.tick(5) == 5.0
    assert await state.tick(2.5) == 7.5
    assert (await state.snapshot()).active_seconds == 7.5


async def test_tick_stops_after_end_or_without_state(client):
    state = make(client)
    await state.load_or_create()
    await state.end()
    assert await state.tick(5) is None
    assert await make(client, app_id="nobody").tick(5) is None


async def test_set_wrapup_flag(client):
    state = make(client)
    await state.load_or_create()
    assert (await state.snapshot()).wrapup is False
    await state.set_wrapup()
    assert (await state.snapshot()).wrapup is True