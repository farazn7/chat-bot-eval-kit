import hashlib
import json
from pathlib import Path
from importlib.resources import files
from .models import Request, Turn


def data_path(name):
    return Path(str(files("chatbot_eval").joinpath("data", name)))


def load_cases(path=None, split=None):
    path = Path(path) if path else data_path("cases.jsonl")
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids, families = set(), {}
    for c in cases:
        for key in ("id", "family", "split", "category", "question", "expected_behavior", "evidence_ids", "history"):
            if key not in c:
                raise ValueError(f"Missing case field: {key}")
        if c["id"] in ids or c["split"] not in {"development", "heldout"}:
            raise ValueError("Duplicate ID or invalid split")
        if c["family"] in families and families[c["family"]] != c["split"]:
            raise ValueError("A scenario family crosses dataset splits")
        if not c["expected_behavior"] or not isinstance(c["evidence_ids"], list):
            raise ValueError("Expected behavior and evidence IDs are required")
        to_request(c)
        ids.add(c["id"])
        families[c["family"]] = c["split"]
    return [c for c in cases if split is None or c["split"] == split]


def to_request(case):
    return Request(case["question"], tuple(Turn(**t) for t in case.get("history", [])))


def verify_freeze():
    manifest = json.loads(data_path("manifest.json").read_text(encoding="utf-8"))
    for name, digest in manifest["sha256"].items():
        if hashlib.sha256(data_path(name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Frozen dataset changed: {name}; create a new version explicitly")
    return manifest
