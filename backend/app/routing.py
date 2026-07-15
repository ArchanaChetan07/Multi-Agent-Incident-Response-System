"""Phase 3: Cost-aware model routing.

Policy: always call the cheap/fast model first. Only escalate to the strong
model if the Critic's confidence falls below CONFIDENCE_THRESHOLD. Tracks
cost for both the actual (cost-aware) run and a hypothetical "always-escalate"
baseline so savings can be reported (a named success metric).
"""
from dataclasses import dataclass, field
from typing import List
from .llm_client import LLMResponse, MODEL_TIERS, MODEL_PRICING
from .config import CONFIDENCE_THRESHOLD


@dataclass
class CostLedger:
    calls: List[LLMResponse] = field(default_factory=list)

    def record(self, resp: LLMResponse):
        self.calls.append(resp)

    @property
    def actual_cost(self) -> float:
        return sum(r.cost_usd for r in self.calls)

    @property
    def baseline_always_strong_cost(self) -> float:
        """What this run would have cost if every call used the strong model."""
        strong_price = MODEL_PRICING[MODEL_TIERS["strong"]]
        total = 0.0
        for r in self.calls:
            total += (r.input_tokens / 1000) * strong_price["input"] + (r.output_tokens / 1000) * strong_price["output"]
        return total

    @property
    def savings_pct(self) -> float:
        baseline = self.baseline_always_strong_cost
        if baseline == 0:
            return 0.0
        return round(100 * (1 - self.actual_cost / baseline), 2)


def should_escalate(confidence: float) -> bool:
    return confidence < CONFIDENCE_THRESHOLD
