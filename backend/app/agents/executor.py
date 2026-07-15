"""Executor agents: run tool calls (query_logs / query_traces / query_pr_diff)
and synthesize a candidate root cause from the gathered evidence."""
import json
from ..llm_client import call_llm, MODEL_TIERS, LLMParseError
from ..models import Incident
from ..tracing import tracer
from ..logging_setup import get_logger

log = get_logger(__name__)


def query_logs(incident: Incident):
    return incident.logs


def query_traces(incident: Incident):
    return incident.stack_traces


def query_pr_diff(incident: Incident):
    return incident.pr_diffs


TOOLS = {
    "query_logs": query_logs,
    "query_traces": query_traces,
    "query_pr_diff": query_pr_diff,
}


def execute(incident: Incident, subtasks, ledger):
    evidence = {}
    with tracer.start_as_current_span("executor.run_subtasks") as span:
        for task in subtasks:
            tool_name = task.get("type")
            tool_fn = TOOLS.get(tool_name)
            if tool_fn is None:
                log.warning(f"Executor: unknown tool '{tool_name}' requested for {incident.id}, skipping")
                continue
            with tracer.start_as_current_span(f"executor.tool.{tool_name}") as tool_span:
                result = tool_fn(incident)
                tool_span.set_attribute("tool.result_count", len(result))
                evidence[tool_name] = result

        prompt = (
            "You are an EXECUTOR agent synthesizing a root cause from evidence. "
            f"Evidence: {json.dumps(evidence)}. Return JSON with root_cause and evidence[]."
        )
        resp = call_llm(prompt, model=MODEL_TIERS["cheap"])
        ledger.record(resp)
        try:
            candidate = resp.json()
        except LLMParseError:
            log.warning(f"Executor: failed to parse LLM output for {incident.id}; no root cause proposed")
            candidate = {"root_cause": None, "evidence": []}
        span.set_attribute("executor.evidence_sources", len(evidence))
        return candidate
