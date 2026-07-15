"""Planner agent: decomposes an incident into investigation sub-tasks."""
from ..llm_client import call_llm, MODEL_TIERS, LLMParseError
from ..models import Incident
from ..tracing import tracer
from ..logging_setup import get_logger

log = get_logger(__name__)

# Fallback plan used if the model's output can't be parsed — keeps the
# pipeline moving with a sane default rather than crashing the request.
DEFAULT_SUBTASKS = [
    {"type": "query_logs", "target": "app-service"},
    {"type": "query_traces", "target": "request-span"},
    {"type": "query_pr_diff", "target": "last-deploy"},
]


def plan(incident: Incident, ledger):
    with tracer.start_as_current_span("planner.decompose") as span:
        span.set_attribute("incident.id", incident.id)
        prompt = (
            "You are the PLANNER agent. Decompose this incident into investigation "
            "subtasks (query_logs, query_traces, query_pr_diff). Incident logs: "
            f"{incident.logs}"
        )
        resp = call_llm(prompt, model=MODEL_TIERS["cheap"])
        ledger.record(resp)
        try:
            subtasks = resp.json().get("subtasks", DEFAULT_SUBTASKS)
        except LLMParseError:
            log.warning(f"Planner: failed to parse LLM output for {incident.id}, using default plan")
            subtasks = DEFAULT_SUBTASKS
        span.set_attribute("planner.subtask_count", len(subtasks))
        return subtasks
