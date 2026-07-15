# Multi-Agent Incident Response System

A cost-aware, hallucination-guarded multi-agent root-cause analysis platform.
Planner → Executor → Critic agent loop, with cost-aware model routing,
full OpenTelemetry tracing, and an adversarial hallucination-guard test suite.

## Architecture

```
frontend (index.html)  --HTTP-->  backend (FastAPI)  --calls-->  orchestrator
                                                                     |
                                                       planner -> executor -> critic
                                                                     |
                                                            LLM client (real API or
                                                            deterministic offline mock)
                                                                     |
                                                        OpenTelemetry spans -> Jaeger
```

- **backend/app/models.py** — Phase 1: canonical `Incident` schema + dataset loader
- **backend/app/agents/** — Phase 2: planner, executor, critic
- **backend/app/routing.py** — Phase 3: cost-aware model routing + savings tracking
- **backend/app/tracing.py** — Phase 4: OpenTelemetry setup
- **backend/tests/test_hallucination_guard.py** — Phase 5: adversarial test suite
- **backend/app/main.py** — Phase 6: FastAPI service
- **frontend/index.html** — Phase 7: triage dashboard
- **eval/evaluate.py** — Phase 8: precision/recall + guard pass-rate + cost report
- **docker-compose.yml, .github/workflows/ci.yml** — Phase 9: infra + CI

## Production hardening (v1.1)

This revision closes several gaps found in a production-readiness review:

| Issue | Fix |
|---|---|
| `GET /report` silently re-ran the full (costly, non-deterministic) pipeline on every call | Reports are now cached on `/investigate` and `/report` returns the cached result; 404s if no investigation has run yet |
| LLM JSON parsing crashed on markdown-fenced or preamble-prefixed model output | `LLMResponse.json()` robustly extracts JSON; agents fail closed (planner uses a default plan, critic defaults to **reject**) on parse failure |
| No retry/timeout handling on real API calls | Exponential backoff on 429/5xx/network errors, explicit timeout, typed `LLMError` |
| No cost ceiling | `MAX_COST_PER_INCIDENT_USD` aborts/skips escalation if a single incident's pipeline cost exceeds the cap |
| CORS wildcard, no auth | `ALLOWED_ORIGINS` and optional `API_AUTH_TOKEN` bearer-auth via env vars |
| No input validation | Payload field/item length caps reject oversized log/diff submissions (422) |
| No persistence | Runtime incidents + reports persist to a JSON-backed store (`DB_PATH`, atomic writes, thread-safe) surviving restarts |
| Docker ran as root, no healthcheck tooling | Non-root user, `curl`-based `HEALTHCHECK`, `.dockerignore` |
| No structured logging | JSON-formatted logs via `logging_setup.py` |
| No API-level tests | `backend/tests/test_api.py` covers auth, validation, 404s, and the report-caching regression |

Relevant env vars (all optional, sane defaults for local dev):

```
ALLOWED_ORIGINS=https://yourapp.com,https://admin.yourapp.com
API_AUTH_TOKEN=some-long-random-token
CONFIDENCE_THRESHOLD=0.6
MAX_COST_PER_INCIDENT_USD=1.00
MAX_FIELD_ITEMS=500
MAX_ITEM_LENGTH=20000
DB_PATH=/app/data/data.db
LLM_MAX_RETRIES=3
LLM_TIMEOUT_SECONDS=30
LOG_LEVEL=INFO
```

## Quickstart (local, no API key required)

The system runs fully offline using a deterministic mock LLM client so you can
develop, test, and evaluate without spending on API calls or needing network
access. Set `ANTHROPIC_API_KEY` to switch to real model calls.

```bash
cd backend
pip install -r requirements.txt

# Run the API
uvicorn app.main:app --reload --port 8000

# In another terminal, serve the frontend
cd ../frontend && python -m http.server 8080
# open http://localhost:8080  (dashboard talks to http://127.0.0.1:8000)
```

## Run tests

```bash
python -m pytest backend/tests/ -v
```

## Run the evaluation report

```bash
python eval/evaluate.py
```

Outputs precision/recall vs. ground truth, hallucination-guard pass rate,
and cost-aware-routing savings vs. an always-escalate baseline.

## Run with Docker

```bash
docker-compose up --build
# API:      http://localhost:8000
# Frontend: http://localhost:8080
# Jaeger UI: http://localhost:16686
```

To export real traces to Jaeger instead of the console, swap
`ConsoleSpanExporter` for `OTLPSpanExporter(endpoint="jaeger:4317", insecure=True)`
in `backend/app/tracing.py`.

## Using the real Anthropic API

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --reload
```

The `llm_client.py` module detects the env var automatically and routes real
calls through `api.anthropic.com`. Cost accounting uses the pricing table in
that file — update it if pricing changes.

## Extending the dataset (Phase 1)

Add new entries to `data/sample_incidents.json` following the `Incident`
schema. Set `"is_adversarial": true` for deliberately fabricated/misleading
incidents used by the hallucination-guard suite.

## Runbook notes

- **Rotating keys:** set `ANTHROPIC_API_KEY` via your deployment platform's
  secrets manager — never commit it.
- **Adding a new tool for the Executor agent:** add a function to
  `backend/app/agents/executor.py`'s `TOOLS` dict and reference it from the
  Planner's subtask types.
- **Adjusting the escalation threshold:** `CONFIDENCE_THRESHOLD` in
  `backend/app/routing.py`.
