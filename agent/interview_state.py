import time
from dataclasses import dataclass

TTL_SECONDS = 6 * 60 * 60

CREATE = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('HSET', KEYS[1], 'current_index', 0, 'followups_used', 0,
           'total_questions', ARGV[1], 'started_at', ARGV[2], 'status', 'active',
           'awaiting_answer', 0)
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
redis.call('HSET', KEYS[2], tostring(idx), ARGV[1])
redis.call('HSET', KEYS[1], 'awaiting_answer', 0, 'current_index', idx + 1,
           'followups_used', 0)
redis.call('EXPIRE', KEYS[1], ARGV[2])
redis.call('EXPIRE', KEYS[2], ARGV[2])
return idx
"""


@dataclass
class StateSnapshot:
    current_index: int
    followups_used: int
    total_questions: int
    started_at: float
    status: str
    awaiting_answer: bool
    elapsed_seconds: float

    @property
    def all_done(self) -> bool:
        return self.current_index >= self.total_questions


class InterviewState:
    """Live interview progress in Redis: current question, follow-ups, time, status, notes."""

    def __init__(self, client, application_id, total_questions: int):
        self.r = client
        self.key = f"interview:{application_id}"
        self.notes_key = f"interview:{application_id}:notes"
        self.total = total_questions
        self._create = client.register_script(CREATE)
        self._advance = client.register_script(ADVANCE)
        self._begin = client.register_script(BEGIN)
        self._record = client.register_script(RECORD)

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
            elapsed_seconds=max(0.0, time.time() - started),
        )

    async def advance(self) -> StateSnapshot | None:
        await self._advance(keys=[self.key], args=[TTL_SECONDS])
        return await self.snapshot()

    async def begin_question(self) -> int:
        """Mark the current question as asked. Safe to repeat: same index each time."""
        return int(await self._begin(keys=[self.key], args=[TTL_SECONDS]))

    async def record_note(self, note: str) -> int:
        """Save a note for the asked question and move on. Safe to repeat: records once."""
        return int(
            await self._record(
                keys=[self.key, self.notes_key], args=[note, TTL_SECONDS]
            )
        )

    async def notes(self) -> dict[int, str]:
        data = await self.r.hgetall(self.notes_key)
        return {int(k): v for k, v in sorted(data.items(), key=lambda kv: int(kv[0]))}

    async def add_followup(self) -> int:
        count = await self.r.hincrby(self.key, "followups_used", 1)
        await self.r.expire(self.key, TTL_SECONDS)
        return count

    async def end(self) -> None:
        await self.r.hset(self.key, "status", "ended")
        await self.r.expire(self.key, TTL_SECONDS)