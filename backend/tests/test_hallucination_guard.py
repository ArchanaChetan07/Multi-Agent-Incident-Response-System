"""Phase 5: Hallucination-guard test suite.

Runs the full agent pipeline against deliberately fabricated/adversarial
incidents and asserts the system rejects them rather than asserting a
fabricated root cause as fact. Target: 100% rejection rate on the trap set.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.models import load_incidents
from backend.app.orchestrator import investigate


def _trap_incidents():
    return [i for i in load_incidents() if i.is_adversarial]


def test_all_traps_rejected():
    traps = _trap_incidents()
    assert len(traps) > 0, "No adversarial incidents found in dataset"
    failures = []
    for inc in traps:
        report = investigate(inc)
        if report["root_cause"] is not None or report["verdict"] == "accept":
            failures.append(inc.id)
    assert not failures, f"Hallucination guard failed on: {failures}"


def test_legitimate_incidents_are_not_over_rejected():
    """Sanity check: the guard shouldn't reject everything indiscriminately."""
    legit = [i for i in load_incidents() if not i.is_adversarial]
    accepted = 0
    for inc in legit:
        report = investigate(inc)
        if report["verdict"] == "accept":
            accepted += 1
    assert accepted >= 1, "Guard is rejecting legitimate incidents too aggressively"


def test_hallucination_pass_rate_report(capsys):
    """Reports the guard pass rate — used as a CI-visible metric, not just pass/fail."""
    traps = _trap_incidents()
    rejected = sum(1 for i in traps if investigate(i)["verdict"] != "accept")
    rate = 100 * rejected / len(traps) if traps else 0
    print(f"\nHallucination-guard pass rate: {rate:.1f}% ({rejected}/{len(traps)})")
    assert rate == 100.0
