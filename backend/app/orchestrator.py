"""Phase 2/3/4: the full planner -> executor -> critic loop, with cost-aware
escalation and end-to-end OpenTelemetry tracing."""
from .agents import planner, executor, critic
from .routing import CostLedger, should_escalate
from .llm_client import MODEL_TIERS, LLMError
from .models import Incident
from .tracing import tracer
from .config import CONFIDENCE_THRESHOLD, MAX_COST_PER_INCIDENT_USD
from .logging_setup import get_logger

log = get_logger(__name__)


class InvestigationError(Exception):
    """Raised when the pipeline cannot complete (e.g. LLM provider outage)."""


def investigate(incident: Incident) -> dict:
    ledger = CostLedger()
    with tracer.start_as_current_span("orchestrator.investigate") as span:
        span.set_attribute("incident.id", incident.id)

        try:
            subtasks = planner.plan(incident, ledger)
            candidate = executor.execute(incident, subtasks, ledger)

            if ledger.actual_cost > MAX_COST_PER_INCIDENT_USD:
                log.error(f"Cost cap exceeded for {incident.id}: ${ledger.actual_cost:.4f}")
                raise InvestigationError(
                    f"Cost cap of ${MAX_COST_PER_INCIDENT_USD} exceeded before critic review"
                )

            verdict = critic.critique(candidate, incident, model=MODEL_TIERS["cheap"], ledger=ledger)

            escalated = False
            if should_escalate(verdict.get("confidence", 0)):
                if ledger.actual_cost > MAX_COST_PER_INCIDENT_USD:
                    log.warning(f"Skipping escalation for {incident.id}: cost cap reached")
                else:
                    escalated = True
                    verdict = critic.critique(candidate, incident, model=MODEL_TIERS["strong"], ledger=ledger)
        except LLMError as e:
            log.error(f"LLM provider error investigating {incident.id}: {e}")
            span.set_attribute("orchestrator.error", str(e))
            raise InvestigationError(f"LLM provider error: {e}") from e

        span.set_attribute("orchestrator.escalated", escalated)
        span.set_attribute("orchestrator.final_confidence", verdict.get("confidence", 0))

        report = {
            "incident_id": incident.id,
            "root_cause": candidate.get("root_cause") if verdict.get("verdict") == "accept" else None,
            "evidence": candidate.get("evidence", []),
            "confidence": verdict.get("confidence", 0),
            "verdict": verdict.get("verdict"),
            "critic_reason": verdict.get("reason"),
            "escalated_to_strong_model": escalated,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "cost_usd": round(ledger.actual_cost, 6),
            "baseline_always_strong_cost_usd": round(ledger.baseline_always_strong_cost, 6),
            "cost_savings_pct": ledger.savings_pct,
        }
        return report
