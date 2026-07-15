"""Phase 6: Backend API service — production-hardened."""
import json
import os
import threading
import time
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from .models import Incident, load_incidents, get_incident
from .orchestrator import investigate, InvestigationError
from .config import ALLOWED_ORIGINS, API_AUTH_TOKEN, MAX_FIELD_ITEMS, MAX_ITEM_LENGTH, DB_PATH
from .logging_setup import get_logger

log = get_logger(__name__)

app = FastAPI(title="Multi-Agent Incident Response System", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# ---------------------------------------------------------------------------
# Lightweight persistence (JSON file + lock). Swap for Postgres in a larger
# deployment; this is enough to survive restarts for a portfolio-scale service.
# ---------------------------------------------------------------------------
_lock = threading.Lock()


def _load_db() -> dict:
    if not os.path.exists(DB_PATH):
        return {"incidents": {}, "reports": {}}
    with open(DB_PATH) as f:
        return json.load(f)


def _save_db(db: dict):
    tmp_path = DB_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(db, f)
    os.replace(tmp_path, DB_PATH)  # atomic on POSIX


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_auth(authorization: Optional[str] = Header(None)):
    if not API_AUTH_TOKEN:
        return  # auth disabled (local dev default)
    expected = f"Bearer {API_AUTH_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")


# ---------------------------------------------------------------------------
# Models with input validation guardrails
# ---------------------------------------------------------------------------
class IncidentIn(BaseModel):
    id: str
    logs: List[str] = []
    stack_traces: List[str] = []
    pr_diffs: List[str] = []
    timeline: List[str] = []

    @field_validator("logs", "stack_traces", "pr_diffs", "timeline")
    @classmethod
    def check_list_bounds(cls, v):
        if len(v) > MAX_FIELD_ITEMS:
            raise ValueError(f"List exceeds max of {MAX_FIELD_ITEMS} items")
        for item in v:
            if len(item) > MAX_ITEM_LENGTH:
                raise ValueError(f"Item exceeds max length of {MAX_ITEM_LENGTH} chars")
        return v

    @field_validator("id")
    @classmethod
    def check_id(cls, v):
        if not v or len(v) > 128:
            raise ValueError("id must be non-empty and under 128 chars")
        return v


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.exception_handler(InvestigationError)
async def investigation_error_handler(request: Request, exc: InvestigationError):
    log.error(f"Investigation failed: {exc}")
    return JSONResponse(status_code=502, content={"detail": f"Investigation failed: {exc}"})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error(f"Unhandled error on {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/incidents")
def list_incidents():
    incidents = load_incidents()
    with _lock:
        db = _load_db()
    runtime_ids = [{"id": i, "is_adversarial": False} for i in db["incidents"]]
    return [{"id": i.id, "is_adversarial": i.is_adversarial} for i in incidents] + runtime_ids


@app.post("/incidents", dependencies=[Depends(require_auth)])
def create_incident(payload: IncidentIn):
    with _lock:
        db = _load_db()
        if payload.id in db["incidents"]:
            raise HTTPException(status_code=409, detail=f"Incident {payload.id} already exists")
        db["incidents"][payload.id] = payload.model_dump()
        _save_db(db)
    log.info(f"Created incident {payload.id}")
    return {"status": "created", "id": payload.id}


def _resolve_incident(incident_id: str) -> Incident:
    with _lock:
        db = _load_db()
    if incident_id in db["incidents"]:
        return Incident(**db["incidents"][incident_id])
    incident = get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return incident


@app.post("/incidents/{incident_id}/investigate", dependencies=[Depends(require_auth)])
def run_investigation(incident_id: str):
    incident = _resolve_incident(incident_id)
    start = time.time()
    report = investigate(incident)
    report["duration_seconds"] = round(time.time() - start, 3)

    with _lock:
        db = _load_db()
        db["reports"][incident_id] = report
        _save_db(db)
    log.info(f"Investigated {incident_id}: verdict={report['verdict']} cost=${report['cost_usd']}")
    return report


@app.get("/incidents/{incident_id}/report")
def get_report(incident_id: str):
    """Returns the cached result of the most recent investigation.
    Does NOT re-run the pipeline — investigations are costly and (with a real
    LLM) non-deterministic, so re-running on every GET would be both wasteful
    and semantically wrong for a 'fetch report' endpoint."""
    _resolve_incident(incident_id)  # 404s if incident doesn't exist at all
    with _lock:
        db = _load_db()
    report = db["reports"].get(incident_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"No investigation has been run yet for {incident_id}. POST /incidents/{incident_id}/investigate first.",
        )
    return report


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness probe: verifies the dataset and DB file are accessible."""
    try:
        load_incidents()
        with _lock:
            _load_db()
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Not ready: {e}")
