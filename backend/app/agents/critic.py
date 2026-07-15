"""Critic agent: challenges the proposed root cause, scores confidence,
and is the primary defense against hallucinated/fabricated conclusions."""
import json
from ..llm_client import call_llm, MODEL_TIERS, LLMParseError
from ..tracing import tracer
from ..logging_setup import get_logger

log = get_logger(__name__)


def critique(candidate: dict, incident, model=MODEL_TIERS["cheap"], ledger=None):
    with tracer.start_as_current_span("critic.review") as span:
        prompt = (
            "You are the CRITIC agent. Challenge this proposed root cause and score your "
            "confidence 0-1. Scrutinize the raw evidence below for signs it is unreliable "
            "(nonexistent classes/files, internally inconsistent or contradictory logs) and "
            "score low confidence if so. "
            f"Candidate: {json.dumps(candidate)} "
            f"[[RAW_EVIDENCE]] logs={incident.logs} diffs={incident.pr_diffs} [[/RAW_EVIDENCE]]"
        )
        resp = call_llm(prompt, model=model)
        if ledger is not None:
            ledger.record(resp)
        try:
            verdict = resp.json()
        except LLMParseError:
            # Fail closed: an unparseable critic response must never be
            # treated as an "accept" — default to rejecting the candidate.
            log.warning(f"Critic: failed to parse LLM output for {incident.id}; failing closed (reject)")
            verdict = {"confidence": 0.0, "verdict": "reject",
                       "reason": "Critic response could not be parsed; failing closed."}
        span.set_attribute("critic.confidence", verdict.get("confidence", 0))
        span.set_attribute("critic.verdict", verdict.get("verdict", "unknown"))
        return verdict
