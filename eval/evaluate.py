"""Phase 8: Evaluation pipeline.

Runs the full agent pipeline against the entire labeled dataset and reports:
- Root-cause precision/recall vs. human-labeled ground truth
- Hallucination-guard pass rate on adversarial incidents
- Cost-aware routing savings vs. an always-escalate baseline
- Full OpenTelemetry tracing coverage note

Run with: python eval/evaluate.py
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app.models import load_incidents
from backend.app.orchestrator import investigate


def evaluate():
    incidents = load_incidents()
    legit = [i for i in incidents if not i.is_adversarial]
    traps = [i for i in incidents if i.is_adversarial]

    tp = fp = fn = 0
    total_cost = total_baseline = 0.0
    escalations = 0

    for inc in legit:
        report = investigate(inc)
        total_cost += report["cost_usd"]
        total_baseline += report["baseline_always_strong_cost_usd"]
        if report["escalated_to_strong_model"]:
            escalations += 1

        predicted_positive = report["verdict"] == "accept" and report["root_cause"] is not None
        # crude correctness check: does predicted root cause share key terms with ground truth
        correct = predicted_positive and inc.ground_truth_root_cause and (
            _overlaps(report["root_cause"], inc.ground_truth_root_cause)
        )
        if predicted_positive and correct:
            tp += 1
        elif predicted_positive and not correct:
            fp += 1
        elif not predicted_positive:
            fn += 1

    trap_rejected = 0
    for inc in traps:
        report = investigate(inc)
        total_cost += report["cost_usd"]
        total_baseline += report["baseline_always_strong_cost_usd"]
        if report["escalated_to_strong_model"]:
            escalations += 1
        if report["verdict"] != "accept":
            trap_rejected += 1

    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    hallucination_pass_rate = 100 * trap_rejected / len(traps) if traps else 0
    savings_pct = round(100 * (1 - total_cost / total_baseline), 2) if total_baseline else 0

    result = {
        "dataset_size": len(incidents),
        "legit_incidents": len(legit),
        "adversarial_incidents": len(traps),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "hallucination_guard_pass_rate_pct": round(hallucination_pass_rate, 1),
        "cost_aware_routing_savings_pct": savings_pct,
        "total_cost_usd": round(total_cost, 6),
        "baseline_always_strong_cost_usd": round(total_baseline, 6),
        "escalations": escalations,
        "tracing": "every agent decision emitted as an OTel span (see backend/app/tracing.py)",
    }
    print(json.dumps(result, indent=2))
    return result


def _overlaps(a: str, b: str) -> bool:
    a_words = set(a.lower().split())
    b_words = set(b.lower().split())
    return len(a_words & b_words) >= 3


if __name__ == "__main__":
    evaluate()
