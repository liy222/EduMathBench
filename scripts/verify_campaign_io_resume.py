"""Archive an IO-only resume implementation and compare every dev request offline."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import eval_engine as engine
import run_development_campaign as campaign


def verify() -> dict:
    original = campaign.OUT / "implementation/development/scripts/eval_engine.py"
    spec = importlib.util.spec_from_file_location("archived_campaign_engine", original)
    archived = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(archived)
    definition = engine.read_json(campaign.CAMPAIGN)
    dev_stage = next(stage for stage in definition["stages"] if stage["name"] == "development")
    manifest = engine.read_json(campaign.ROOT / dev_stage["manifest"])
    comparisons = []
    for entry in manifest["models"]:
        cfg = engine.read_json(campaign.ROOT / entry["config"])
        cfg["data_root"] = str((campaign.ROOT / cfg["data_root"]).resolve())
        cfg = engine.normalize_config(cfg)
        root = Path(cfg["data_root"])
        items, info = engine.load_dataset(root, "dev")
        items = engine.prioritize_items(items, cfg)
        for item in items:
            old_blocks, old_skip, _ = archived.image_content(item, root, True, minimum_dimension=32)
            new_blocks, new_skip, _ = engine.image_content(item, root, True, minimum_dimension=32)
            if old_skip or new_skip:
                raise engine.EvaluationError("Image preparation unexpectedly failed in IO comparison")
            before = archived.build_request(item, cfg["backend"], old_blocks)
            after = engine.build_request(item, cfg["backend"], new_blocks)
            if engine.json_bytes(before) != engine.json_bytes(after):
                raise engine.EvaluationError("Request contents changed during the IO repair")
            comparisons.append({"model": cfg["backend"]["model"], "id": item["id"], "request_sha256": engine.digest(after)})
    current_hash = engine.file_sha256(Path(engine.__file__))
    index = {"stages": {}}
    for stage in definition["stages"]:
        name = stage["name"]
        extra = campaign.OUT / "implementation" / (name + "_io_retry_v3")
        if extra.exists() and engine.file_sha256(extra / "scripts/eval_engine.py") != current_hash:
            raise engine.EvaluationError("Refusing to overwrite an earlier resume implementation")
        campaign.snapshot(name + "_io_retry_v3", campaign.ROOT / stage["manifest"])
        index["stages"][name] = [
            {"directory": f"runs/campaign_1000/implementation/{name}", "scope": "initial"},
            {"directory": f"runs/campaign_1000/implementation/{name}_io_retry_v2", "scope": "Prepared IO-only candidate, offline comparison only; not used for remote calls"},
            {"directory": f"runs/campaign_1000/implementation/{name}_io_retry_v3", "scope": "IO replacement retry, explicit interrupted reservation accounting and resume source history"},
        ]
    engine.write_json(campaign.OUT / "implementation/implementation_index.json", index)
    report = {
        "passed": True, "external_requests": 0, "requests_compared": len(comparisons),
        "models": len(manifest["models"]), "questions_per_model": len(items),
        "original_engine_sha256": engine.file_sha256(original), "resume_engine_sha256": current_hash,
        "source_manifest_sha256": info["manifest_sha256"],
        "request_comparison_sha256": engine.digest(comparisons),
        "scope": "Only atomic-write retries, interruption bookkeeping and implementation history changed; all 900 request JSON bodies are byte-identical.",
    }
    engine.write_json(campaign.OUT / "io_resume_verification.json", report)
    return report


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False))
