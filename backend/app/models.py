"""Phase 1: Data layer — canonical Incident schema + dataset loader."""
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "sample_incidents.json")


@dataclass
class Incident:
    id: str
    logs: List[str] = field(default_factory=list)
    stack_traces: List[str] = field(default_factory=list)
    pr_diffs: List[str] = field(default_factory=list)
    timeline: List[str] = field(default_factory=list)
    ground_truth_root_cause: Optional[str] = None
    ground_truth_confidence: Optional[float] = None
    is_adversarial: bool = False  # True = deliberately fabricated/misleading (Phase 5)


def load_incidents() -> List[Incident]:
    with open(DATA_PATH) as f:
        raw = json.load(f)
    return [Incident(**item) for item in raw]


def get_incident(incident_id: str) -> Optional[Incident]:
    for inc in load_incidents():
        if inc.id == incident_id:
            return inc
    return None
