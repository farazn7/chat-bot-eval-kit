"""Capture-only experiment runner. Semantic evaluation arrives in phase two."""
from datetime import datetime, timezone
from .dataset import to_request


def run(cases, adapter, *, target, dataset_version="custom", max_calls=60):
    if not cases or max_calls < len(cases):
        raise ValueError("Select at least one case and allow enough calls; no partial silent run")
    records = []
    for case in cases:
        record = {"id": case["id"], "category": case["category"], "question": case["question"],
                  "history": case.get("history", []), "family": case["family"], "split": case["split"],
                  "expected_behavior": case["expected_behavior"], "evidence_ids": case["evidence_ids"]}
        try:
            record.update(status="captured", response=adapter.ask(to_request(case)).to_dict())
        except Exception as exc:
            # Do not publish arbitrary exception text: it may contain credentials or bodies.
            record.update(status="error", error_type=type(exc).__name__)
        records.append(record)
    return {"schema_version": 1, "stage": "phase-one-capture-only", "quality_scored": False,
            "target": target, "dataset_version": dataset_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": {"cases": len(records), "captured": sum(r["status"] == "captured" for r in records),
                        "errors": sum(r["status"] == "error" for r in records)}, "records": records}
