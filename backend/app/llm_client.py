"""
LLM client abstraction.

Uses the real Anthropic API when ANTHROPIC_API_KEY is set in the environment.
Otherwise falls back to a deterministic mock so the full pipeline, tests, and
CI can run without network access or a key.

Production hardening:
- Retries with exponential backoff on transient HTTP/network errors
- Explicit timeout
- Robust JSON extraction (real model output may include markdown fences or
  preamble text) with a typed LLMParseError raised on failure so callers can
  fail closed instead of crashing
"""
import os
import re
import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass

from .config import LLM_MAX_RETRIES, LLM_TIMEOUT_SECONDS
from .logging_setup import get_logger

log = get_logger(__name__)

USE_REAL_API = bool(os.environ.get("ANTHROPIC_API_KEY"))

MODEL_TIERS = {
    "cheap": "claude-haiku-4-5-20251001",
    "strong": "claude-sonnet-5",
}

MODEL_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.001, "output": 0.005},
    "claude-sonnet-5": {"input": 0.003, "output": 0.015},
}


class LLMError(Exception):
    """Raised on unrecoverable LLM call failure (network/API)."""


class LLMParseError(Exception):
    """Raised when the model's response can't be parsed as the expected JSON."""


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def cost_usd(self) -> float:
        p = MODEL_PRICING.get(self.model, {"input": 0, "output": 0})
        return (self.input_tokens / 1000) * p["input"] + (self.output_tokens / 1000) * p["output"]

    def json(self) -> dict:
        """Robustly extract a JSON object from model output. Real models
        sometimes wrap JSON in markdown fences or add a sentence before/after."""
        text = self.text.strip()
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        candidate = fence_match.group(1) if fence_match else text
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass
        raise LLMParseError(f"Could not parse JSON from model output: {text[:200]!r}")


def _mock_response(prompt: str, model: str) -> LLMResponse:
    """Deterministic, content-aware mock so tests are stable and offline-runnable."""
    input_tokens = max(50, len(prompt) // 4)
    output_tokens = 120
    lower = prompt.lower()

    if "planner" in lower:
        text = json.dumps({
            "subtasks": [
                {"type": "query_logs", "target": "app-service"},
                {"type": "query_traces", "target": "request-span"},
                {"type": "query_pr_diff", "target": "last-deploy"},
            ]
        })
    elif "critic" in lower:
        evidence_marker = lower.find("[[raw_evidence]]")
        evidence_text = lower[evidence_marker:] if evidence_marker != -1 else lower
        adversarial_signals = ["does_not_exist", "nonexistent", "fake.py", "quantum_flux",
                                "fabricated event", "phantom", "unrelated.md"]
        if any(sig in evidence_text for sig in adversarial_signals):
            text = json.dumps({"confidence": 0.15, "verdict": "reject",
                                "reason": "Evidence is inconsistent or unverifiable; refusing to assert a root cause."})
        else:
            text = json.dumps({"confidence": 0.82, "verdict": "accept",
                                "reason": "Evidence across logs, traces, and diff is consistent."})
    else:
        text = json.dumps({
            "root_cause": "Null pointer introduced by unvalidated config field in last deploy",
            "evidence": ["log:NullPointerException at ConfigLoader.java:42",
                         "diff:removed null-check in ConfigLoader#load"],
        })

    return LLMResponse(text=text, model=model, input_tokens=input_tokens, output_tokens=output_tokens)


def _call_real_api(prompt: str, model: str) -> LLMResponse:
    last_error = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                    "anthropic-version": "2023-06-01",
                },
                data=json.dumps({
                    "model": model,
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt + "\n\nRespond with ONLY valid JSON, no other text."}],
                }).encode(),
            )
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read())
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage", {})
            return LLMResponse(
                text=text, model=model,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 429 or e.code >= 500:
                log.warning(f"LLM call attempt {attempt} failed with HTTP {e.code}, retrying...")
                time.sleep(min(2 ** attempt, 10))
                continue
            raise LLMError(f"Anthropic API error {e.code}: {e.read()[:300]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            last_error = e
            log.warning(f"LLM call attempt {attempt} failed with {e}, retrying...")
            time.sleep(min(2 ** attempt, 10))
            continue
    raise LLMError(f"Anthropic API call failed after {LLM_MAX_RETRIES} attempts: {last_error}")


def call_llm(prompt: str, model: str = MODEL_TIERS["cheap"]) -> LLMResponse:
    if not USE_REAL_API:
        return _mock_response(prompt, model)
    return _call_real_api(prompt, model)
