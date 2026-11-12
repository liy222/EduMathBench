"""Check deterministic API image preparation offline, leaving source assets intact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import eval_engine as engine


ROOT = Path(__file__).resolve().parents[1]


def check(data_root: Path, minimum: int, output: Path) -> dict:
    if isinstance(minimum, bool) or not isinstance(minimum, int) or not 1 <= minimum <= 1024:
        raise engine.EvaluationError("minimum must be an integer between 1 and 1024")
    data_root = data_root.resolve()
    items, info = engine.load_dataset(data_root, "all")
    issues, evidence = [], []
    asset_count = padded_count = 0
    for item in items:
        records = []
        _, status, error = engine.image_content(
            item, data_root, True, minimum_dimension=minimum, processing_evidence=records,
        )
        if status:
            issues.append({"id": item["id"], "status": status, "error": error})
        for record in records:
            asset_count += 1
            if min(record["derived_dimensions"]) < minimum:
                issues.append({"id": item["id"], "status": "minimum_dimension_failed"})
            source_path = engine.contained_path(data_root, record["path"])
            if engine.file_sha256(source_path) != record["source_sha256"]:
                issues.append({"id": item["id"], "status": "source_changed"})
            if record["operation"] == "white_padding":
                padded_count += 1
                evidence.append({"id": item["id"], **record})
    report = {
        "scope": "offline image preparation for future runs only; no API retest",
        "minimum_dimension": minimum, "questions_checked": len(items),
        "asset_occurrences_checked": asset_count, "padded_asset_occurrences": padded_count,
        "issues": issues, "passed": not issues, "external_requests": 0,
        "source_manifest_sha256": info["manifest_sha256"],
        "source_input_sha256": info["input_sha256"],
        "engine_sha256": engine.file_sha256(Path(engine.__file__)),
        "padding_evidence": evidence,
    }
    engine.write_json(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data/benchmark_web_v0.3")
    parser.add_argument("--minimum", type=int, default=32)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/domestic_six_followup_offline_images.json")
    args = parser.parse_args()
    result = check(args.data_root, args.minimum, args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "padding_evidence"}, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)
