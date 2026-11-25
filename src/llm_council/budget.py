"""Budget tracking: measured vs estimated vs unavailable usage, limits and reserve."""

from __future__ import annotations

import time
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .config import Limits
from .ontology import BudgetSnapshot, StopReason


def estimate_tokens(text: str) -> int:
    """Heuristic estimate (labelled as such wherever it is displayed)."""
    return max(1, len(text) // 4)


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: float
    model_calls_used: int = 0
    tokens_estimated: int = 0
    tokens_measured: int = 0
    cost_usd: Optional[float] = None
    cost_status: str = "unavailable"
    calls_with_cost: int = 0
    verification_calls_used: int = 0
    leader_challenges_used: int = 0
    reopens_used: int = 0
    reframes_used: int = 0
    elapsed_override: Optional[float] = None  # tests may freeze time

    @classmethod
    def start(cls) -> "Budget":
        return cls(started_at=time.time())

    def elapsed(self) -> float:
        if self.elapsed_override is not None:
            return self.elapsed_override
        return time.time() - self.started_at

    def charge(self, *, calls: int = 1, tokens_measured: Optional[int] = None,
               tokens_estimated: Optional[int] = None, cost_usd: Optional[float] = None) -> None:
        self.model_calls_used += calls
        if tokens_measured is not None:
            self.tokens_measured += tokens_measured
        if tokens_estimated is not None:
            self.tokens_estimated += tokens_estimated
        if cost_usd is not None:
            self.cost_usd = (self.cost_usd or 0.0) + cost_usd
            self.calls_with_cost += calls
        if self.calls_with_cost == 0:
            self.cost_status = "unavailable"
        elif self.calls_with_cost == self.model_calls_used:
            self.cost_status = "measured"
        else:
            self.cost_status = "partial"

    def remaining_calls(self, limits: Limits) -> int:
        return limits.max_model_calls - self.model_calls_used

    def deliberation_calls_available(self, limits: Limits) -> int:
        return self.remaining_calls(limits) - limits.finalisation_reserve_calls

    def limit_hit(self, limits: Limits) -> Optional[StopReason]:
        if self.deliberation_calls_available(limits) <= 0:
            return StopReason.BUDGET_CALLS
        if (self.tokens_estimated + self.tokens_measured) >= limits.max_tokens_estimate:
            return StopReason.BUDGET_TOKENS
        if self.elapsed() >= limits.max_elapsed_seconds:
            return StopReason.BUDGET_TIME
        if limits.max_cost_usd is not None and self.cost_usd is not None and self.cost_usd >= limits.max_cost_usd:
            return StopReason.BUDGET_COST
        return None

    def can_afford(self, limits: Limits, calls: int) -> bool:
        return self.deliberation_calls_available(limits) >= calls

    def snapshot(self, limits: Limits) -> BudgetSnapshot:
        return BudgetSnapshot(
            model_calls_used=self.model_calls_used,
            model_calls_limit=limits.max_model_calls,
            tokens_estimated=self.tokens_estimated,
            tokens_measured=self.tokens_measured,
            tokens_limit=limits.max_tokens_estimate,
            elapsed_seconds=round(self.elapsed(), 3),
            elapsed_limit=limits.max_elapsed_seconds,
            cost_usd=self.cost_usd,
            cost_limit=limits.max_cost_usd,
            cost_status=self.cost_status if self.cost_status in ("measured", "unavailable", "partial") else "unavailable",
        )
