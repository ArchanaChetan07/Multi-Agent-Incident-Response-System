import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.models import get_incident
from backend.app.orchestrator import investigate


def test_investigate_returns_full_report_shape():
    incident = get_incident("INC-001")
    report = investigate(incident)
    for key in ["incident_id", "root_cause", "confidence", "verdict",
                "cost_usd", "baseline_always_strong_cost_usd", "cost_savings_pct"]:
        assert key in report


def test_legit_incident_produces_root_cause():
    incident = get_incident("INC-002")
    report = investigate(incident)
    assert report["root_cause"] is not None
    assert report["confidence"] > 0.5
