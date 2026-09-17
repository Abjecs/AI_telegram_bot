from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EntryPlan:
    side: str
    entry: float
    stop: float
    take: float
    risk_score: int
    rationale: str


def risk_allowed(score: int, max_score: int) -> bool:
    return 1 <= score <= 10 and score <= max_score
