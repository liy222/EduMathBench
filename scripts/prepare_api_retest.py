"""Create the user-authorized, 12-request targeted API retest configuration."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import eval_engine as engine


ROOT = Path(__file__).resolve().parents[1]
TEXT7 = "EMB-P-G7-000009"
IMAGE7 = "EMB-P-WEB2-TIKU-1899101"
TEXT8 = "EMB-P-G8-000014"
IMAGE8 = "EMB-P-WEB2-TIKU-1920731"
SMALL_IMAGE = "EMB-P-WEB2-TIKU-1754090"


def prepare() -> dict:
    output = ROOT / "config/evaluation_retest_12"
    output.mkdir(exist_ok=True)
    manifest_path = ROOT / "config/evaluation_retest_12.json"
    if (ROOT / "runs/domestic_four_retest_12/batch.json").exists():
        raise engine.EvaluationError("This retest has already started; do not overwrite its configurations")
    source = engine.read_json(ROOT / "config/evaluation_domestic_six_followup.json")
    by_name = {entry["output_name"]: entry for entry in source["models"]}
    allocations = [
        ("qwen3.8-flash", 3, [SMALL_IMAGE, TEXT7, IMAGE7], "small_image_and_text_control"),
        ("doubao-seed-2.1-lite", 3, [SMALL_IMAGE, TEXT7, IMAGE7], "small_image_and_text_control"),
        ("kimi-k3", 5, [TEXT7, IMAGE7, TEXT8, IMAGE8, SMALL_IMAGE], "rate_limit_and_image_retest"),
        ("minimax-m3.1-flash", 1, [TEXT7], "account_text_only"),
    ]
    entries = []
    for name, limit, priorities, goal in allocations:
        entry = by_name[name]
        path = engine.contained_path(ROOT, entry["config"])
        config = copy.deepcopy(engine.read_json(path))
        config.update(
            max_requests=limit, priority_ids=priorities,
            preflight_status="not_run", probe_goal=goal,
            description=f"用户授权新增12次的问题项复测；本模型最多{limit}次，包含重试。",
        )
        target = output / path.name
        engine.normalize_config(config)
        engine.write_json(target, config)
        entries.append({**entry, "config": target.relative_to(ROOT).as_posix(), "probe_goal": goal})
    manifest = {
        "version": "domestic-four-retest-20261111-v1", "stage": "domestic_four_retest",
        "description": "仅复测首轮问题项，不是正式数学成绩或六模型完整比较。",
        "split": "debug", "max_requests_total": 12,
        "budget_authorization": "用户在本轮明确批准新增最多12次，四家问题项，含失败重试。",
        "expected_data_manifest_sha256": source["expected_data_manifest_sha256"],
        "models": entries,
    }
    engine.write_json(manifest_path, manifest)
    return {"manifest": str(manifest_path), "request_limit": 12, "models": 4, "external_requests": 0}


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False))
