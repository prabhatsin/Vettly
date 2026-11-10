from dataclasses import dataclass, field
from typing import Any

STAGES = ["screener", "technical", "behavioral"]

@dataclass
class SessionData:
    application_id: str
    plan: dict
    ranges: dict[str, tuple[int, int]]
    candidate_name: str = ""
    stage: str = "screener"
    summaries: dict[str, str] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    state: Any = None
    on_closed: Any = None

def split_ranges(total: int) -> dict[str, tuple[int, int]]:
    edge = max(1, round(total * 0.25))
    return {"screener": (0, edge), "technical": (edge, total - edge), "behavioral": (total - edge, total)}