import time
from dataclasses import dataclass

TTL_SECONDS = 6 * 60 * 60

CREATE = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('HSET', KEYS[1], 'current_index', 0, 'followups_used', 0,
           'total_questions', ARGV[1], 'started_at', ARGV[2], 'status', 'active',
           'awaiting_answer', 0, 'active_seconds', 0, 'wrapup', 0, 'stage', 'screener')
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""

ADVANCE = """
local idx = tonumber(redis.call('HGET', KEYS[1], 'current_index'))
local total = tonumber(redis.call('HGET', KEYS[1], 'total_questions'))
if idx == nil then return -1 end
if idx < total then
  idx = idx + 1
  redis.call('HSET', KEYS[1], 'current_index', idx, 'followups_used', 0)
end
redis.call('EXPIRE', KEYS[1], ARGV[1])
return idx
"""

# returns the question index to ask, or -1 all done, -2 no state, -3 ended
BEGIN = """
if redis.call('EXISTS', KEYS[1]) == 0 then return -2 end
if redis.call('HGET', KEYS[1], 'status') == 'ended' then return -3 end
local idx = tonumber(redis.call('HGET', KEYS[1], 'current_index'))
local total = tonumber(redis.call('HGET', KEYS[1], 'total_questions'))
if idx >= total then return -1 end
redis.call('HSET', KEYS[1], 'awaiting_answer', 1)
redis.call('EXPIRE', KEYS[1], ARGV[1])
return idx
"""

# returns the index recorded, or -1 nothing to record, -2 no state, -3 ended
RECORD = """
if redis.call('EXISTS', KEYS[1]) == 0 then return -2 end
if redis.call('HGET', KEYS[1], 'status') == 'ended' then return -3 end
if redis.call('HGET', KEYS[1], 'awaiting_answer') ~= '1' then return -1 end
local idx = tonumber(redis.call('HGET', KEYS[1], 'current_index'))
local expected = tonumber(ARGV[3])
if expected >= 0 and idx ~= expected then return -1 end
redis.call('HSET', KEYS[2], tostring(idx), ARGV[1])
redis.call('HSET', KEYS[1], 'awaiting_answer', 0, 'current_index', idx + 1,
           'followups_used', 0)
redis.call('EXPIRE', KEYS[1], ARGV[2])
redis.call('EXPIRE', KEYS[2], ARGV[2])
return idx
"""

# returns the new follow-up count, or -1 cap reached, -2 no state, -3 ended, -4 no open question
FOLLOWUP = """
if redis.call('EXISTS', KEYS[1]) == 0 then return -2 end
if redis.call('HGET', KEYS[1], 'status') == 'ended' then return -3 end
if redis.call('HGET', KEYS[1], 'awaiting_answer') ~= '1' then return -4 end
local used = tonumber(redis.call('HGET', KEYS[1], 'followups_used'))
if used >= tonumber(ARGV[1]) then return -1 end
redis.call('HSET', KEYS[1], 'followups_used', used + 1)
redis.call('EXPIRE', KEYS[1], ARGV[2])
return used + 1
"""

# adds connected seconds; returns the new total, or '-1' if there is no active state
TICK = """
if redis.call('EXISTS', KEYS[1]) == 0 then return '-1' end
if redis.call('HGET', KEYS[1], 'status') ~= 'active' then return '-1' end
local total = redis.call('HINCRBYFLOAT', KEYS[1], 'active_seconds', ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return total
"""


@dataclass
class StateSnapshot:
    current_index: int
    followups_used: int
    total_questions: int
    started_at: float
    status: str
    awaiting_answer: bool
    active_seconds: float
    wrapup: bool
    elapsed_seconds: float

    @property
    def all_done(self) -> bool:
        return self.current_index >= self.total_questions


class InterviewState:
    """Live interview progress in Redis: question, follow-ups, connected time, status, notes."""

    def __init__(self, client, application_id, total_questions: int):
        self.r = client
        self.key = f"interview:{application_id}"
        self.notes_key = f"interview:{application_id}:notes"
        self.summaries_key = f"interview:{application_id}:summaries"
        self.total = total_questions
        self._create = client.register_script(CREATE)
        self._advance = client.register_script(ADVANCE)
        self._begin = client.register_script(BEGIN)
        self._record = client.register_script(RECORD)
        self._followup = client.register_script(FOLLOWUP)
        self._tick = client.register_script(TICK)

    async def load_or_create(self) -> StateSnapshot:
        await self._create(
            keys=[self.key], args=[self.total, time.time(), TTL_SECONDS]
        )
        return await self.snapshot()

    async def snapshot(self) -> StateSnapshot | None:
        data = await self.r.hgetall(self.key)
        if not data:
            return None
        started = float(data["started_at"])
        return StateSnapshot(
            current_index=int(data["current_index"]),
            followups_used=int(data["followups_used"]),
            total_questions=int(data["total_questions"]),
            started_at=started,
            status=data["status"],
            awaiting_answer=data.get("awaiting_answer", "0") == "1",
            active_seconds=float(data.get("active_seconds", "0")),
            wrapup=data.get("wrapup", "0") == "1",
            elapsed_seconds=max(0.0, time.time() - started),
        )

    async def advance(self) -> StateSnapshot | None:
        await self._advance(keys=[self.key], args=[TTL_SECONDS])
        return await self.snapshot()

    async def begin_question(self) -> int:
        """Mark the current question as asked. Safe to repeat: same index each time."""
        return int(await self._begin(keys=[self.key], args=[TTL_SECONDS]))

    async def record_note(self, note: str, expected_index: int | None = None) -> int:
        """Save a note for the asked question and move on.

        If expected_index is given and is not the open question, nothing is recorded
        (a repeated call is a no-op). Returns the index recorded, or -1 nothing recorded,
        -2 no state, -3 ended.
        """
        expected = -1 if expected_index is None else expected_index
        return int(
            await self._record(
                keys=[self.key, self.notes_key], args=[note, TTL_SECONDS, expected]
            )
        )

    async def try_followup(self, cap: int) -> int:
        """Use one follow-up for the open question, unless the cap is reached."""
        return int(await self._followup(keys=[self.key], args=[cap, TTL_SECONDS]))

    async def tick(self, seconds: float) -> float | None:
        """Add connected time. Returns the new total, or None if the interview is not active."""
        value = float(await self._tick(keys=[self.key], args=[seconds, TTL_SECONDS]))
        return None if value < 0 else value

    async def set_wrapup(self) -> None:
        if await self.r.exists(self.key):
            await self.r.hset(self.key, "wrapup", 1)

    async def notes(self) -> dict[int, str]:
        data = await self.r.hgetall(self.notes_key)
        return {int(k): v for k, v in sorted(data.items(), key=lambda kv: int(kv[0]))}

    async def add_followup(self) -> int:
        count = await self.r.hincrby(self.key, "followups_used", 1)
        await self.r.expire(self.key, TTL_SECONDS)
        return count

    async def get_stage(self) -> str:
        """Current interview stage. Defaults to 'screener' for older state without one."""
        return await self.r.hget(self.key, "stage") or "screener"

    async def set_stage(self, stage: str) -> None:
        if await self.r.exists(self.key):
            await self.r.hset(self.key, "stage", stage)
            await self.r.expire(self.key, TTL_SECONDS)

    async def save_summary(self, stage: str, text: str) -> None:
        await self.r.hset(self.summaries_key, stage, text)
        await self.r.expire(self.summaries_key, TTL_SECONDS)

    async def summaries(self) -> dict[str, str]:
        return await self.r.hgetall(self.summaries_key)

    async def end(self) -> None:
        await self.r.hset(self.key, "status", "ended")
        await self.r.expire(self.key, TTL_SECONDS)