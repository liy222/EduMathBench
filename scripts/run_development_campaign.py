"""Run the explicitly authorized precheck then dev150 campaign, never test."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil

import eval_batch
import eval_engine as engine
from eval_credentials import load_project_env


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "config/evaluation_campaign_1000.json"
OUT = ROOT / "runs/campaign_1000"
PROBLEM = "EMB-P-WEB2-TIKU-1754090"
PRIORITIES = [PROBLEM, "EMB-P-G7-000009", "EMB-P-WEB2-TIKU-1899101", "EMB-P-G8-000014", "EMB-P-WEB2-TIKU-1920731", "EMB-P-WEB2-TIKU-1904344"]


def prepare() -> dict:
    if (OUT / "campaign.json").exists():
        raise engine.EvaluationError("Campaign already started; use run --resume without regenerating configurations")
    source = engine.read_json(ROOT / "config/evaluation_domestic_six_followup.json")
    entries = {row["output_name"]: row for row in source["models"]}
    stages = []
    definitions = [
        ("precheck", "domestic_two_precheck", "debug", 4, 8, 1, ["qwen3.8-flash", "minimax-m3.1-flash"]),
        ("development", "domestic_six_development", "dev", 165, 990, 3,
         ["kimi-k3", "deepseek-flash", "qwen3.8-flash", "glm-5.3-flash", "minimax-m3.1-flash", "doubao-seed-2.1-lite"]),
    ]
    for name, stage, split, limit, total, workers, models in definitions:
        config_dir = ROOT / f"config/campaign_1000/{name}"
        config_dir.mkdir(parents=True, exist_ok=True)
        selected = []
        for key in models:
            entry = entries[key]
            old_path = engine.contained_path(ROOT, entry["config"])
            config = copy.deepcopy(engine.read_json(old_path))
            config.update(
                split=split, max_requests=limit, priority_ids=PRIORITIES,
                description=f"本轮新增最多1000次授权下的{name}阶段，模型上限{limit}次，含重试；不运行test。",
                preflight_status="campaign_prepared_not_run",
            )
            config["backend"].update(max_output_tokens=8192, minimum_image_dimension=32)
            config.pop("output_limit_note", None)
            if split == "dev":
                config["protocol_note"] = "六模型同一dev150/完整次序/提示emb-choice-v1/8192输出上限；思考与温度按各家支持情况如实记录。"
            engine.normalize_config(config)
            target = config_dir / old_path.name
            engine.write_json(target, config)
            selected.append({**entry, "config": target.relative_to(ROOT).as_posix()})
        manifest_path = ROOT / f"config/evaluation_{'precheck' if name == 'precheck' else 'dev150'}_1000.json"
        manifest = {
            "version": f"campaign-1000-{name}-v1", "stage": stage, "split": split,
            "max_requests_total": total, "parallel_workers": workers,
            "expected_data_manifest_sha256": source["expected_data_manifest_sha256"],
            "models": selected,
            "budget_authorization": "用户明确批准新增最多1000次，按顺序完成补验与六家150题开发集，含重试。",
        }
        engine.write_json(manifest_path, manifest)
        stages.append({"name": name, "manifest": manifest_path.relative_to(ROOT).as_posix(), "output": f"runs/campaign_1000/{name}", "max_requests": total})
    campaign = {
        "version": "development-campaign-1000-v1", "authorized_max_requests": 1000,
        "allocated_max_requests": 998, "unallocated_reserve": 2,
        "previous_authorized_requests": 72, "formal_test_authorized": False,
        "authorization": "用户选择新增最多1000次，先补验再六家各150题开发集；包含失败重试。",
        "stages": stages,
    }
    engine.write_json(CAMPAIGN, campaign)
    return campaign


def snapshot(name: str, manifest_path: Path) -> None:
    manifest = engine.read_json(manifest_path)
    relative_paths = [
        "scripts/eval_engine.py", "scripts/eval_batch.py", "scripts/eval_credentials.py",
        "scripts/run_development_campaign.py", "config/evaluation_campaign_1000.json",
        manifest_path.relative_to(ROOT).as_posix(),
        *[row["config"] for row in manifest["models"]],
    ]
    output = OUT / "implementation" / name
    records = []
    for relative in relative_paths:
        source = engine.contained_path(ROOT, relative)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        records.append({"path": relative, "sha256": engine.file_sha256(target)})
    engine.write_json(output / "snapshot_manifest.json", {"files": records, "credentials_copied": False})


def precheck_gate(stage_output: Path) -> dict:
    goals = {}
    for name in ("qwen3.8-flash", "minimax-m3.1-flash"):
        detail = engine.read_json(stage_output / name / "items" / engine.item_filename(PROBLEM))
        accepted = any(a.get("status") == "received" for a in detail.get("attempts", []))
        truncated = any(
            choice.get("finish_reason") == "length"
            for a in detail.get("attempts", [])
            for choice in (a.get("raw_response", {}).get("choices", []) if isinstance(a.get("raw_response"), dict) else [])
        )
        padded = [p for p in detail.get("image_processing", []) if p.get("source_dimensions") == [8, 35]]
        padding_ok = len(padded) == 4 and all(p.get("derived_dimensions") == [32, 35] for p in padded)
        goals[name] = {"problem_status": detail.get("status"), "received": accepted, "truncated": truncated, "small_images_padded": padding_ok,
                       "passed": detail.get("status") == "ok" and accepted and not truncated and padding_ok}
    return {"passed": all(g["passed"] for g in goals.values()), "goals": goals}


def campaign_identity(campaign: dict) -> dict:
    records = []
    for stage in campaign["stages"]:
        manifest_path = engine.contained_path(ROOT, stage["manifest"])
        manifest = engine.read_json(manifest_path)
        records.append({"manifest": stage["manifest"], "sha256": engine.file_sha256(manifest_path),
                        "configs": [{"path": row["config"], "sha256": engine.file_sha256(engine.contained_path(ROOT, row["config"]))} for row in manifest["models"]]})
    return {"campaign_sha256": engine.file_sha256(CAMPAIGN), "stages": records,
            "prompt_sha256": engine.digest({"version": engine.PROMPT_VERSION, "system_prompt": engine.SYSTEM_PROMPT})}


def request_accounting(campaign: dict) -> dict:
    by_stage, inflight = {}, 0
    for stage in campaign["stages"]:
        manifest = engine.read_json(engine.contained_path(ROOT, stage["manifest"]))
        total = 0
        for row in manifest["models"]:
            path = engine.contained_path(ROOT, stage["output"]) / row["output_name"] / "run.json"
            if path.exists():
                metadata = engine.read_json(path)
                reservations = metadata.get("remote_attempts")
                if not isinstance(reservations, list):
                    raise engine.EvaluationError("Request accounting missing from existing model metadata")
                total += len(reservations)
                inflight += sum(a.get("state") == "reserved" for a in reservations)
                cap = engine.read_json(engine.contained_path(ROOT, row["config"]))["max_requests"]
                if len(reservations) > cap:
                    raise engine.EvaluationError("Per-model cap exceeded")
        if total > stage["max_requests"]:
            raise engine.EvaluationError("Stage request cap exceeded")
        by_stage[stage["name"]] = total
    current = sum(by_stage.values())
    if current > campaign["authorized_max_requests"]:
        raise engine.EvaluationError("Campaign request cap exceeded")
    return {"new_requests": current, "by_stage": by_stage, "inflight": inflight, "authorized_max_requests": campaign["authorized_max_requests"], "previous_requests": 72, "cumulative_requests": 72 + current}


def run(*, resume: bool = False) -> dict:
    campaign = engine.read_json(CAMPAIGN)
    if campaign.get("authorized_max_requests") != 1000 or sum(stage["max_requests"] for stage in campaign["stages"]) > 1000:
        raise engine.EvaluationError("Campaign allocation does not match the explicit 1000-request authorization")
    if [stage.get("name") for stage in campaign["stages"]] != ["precheck", "development"]:
        raise engine.EvaluationError("Campaign must run precheck then development, exactly once each")
    load_project_env()
    identity = campaign_identity(campaign)
    # Validate both stages before sending any new API request.
    for stage in campaign["stages"]:
        manifest = engine.read_json(engine.contained_path(ROOT, stage["manifest"]))
        expected_stage, expected_split = ("domestic_two_precheck", "debug") if stage["name"] == "precheck" else ("domestic_six_development", "dev")
        if manifest.get("stage") != expected_stage or manifest.get("split") != expected_split:
            raise engine.EvaluationError("Campaign stage/split does not match the authorized sequence")
        report = eval_batch.check(engine.contained_path(ROOT, stage["manifest"]), engine.contained_path(ROOT, stage["output"]))
        if not report["ready_for_api"]:
            raise engine.EvaluationError(f"Local readiness failed for {stage['name']}")
        if not 0 < report["allocated_request_limit"] <= manifest["max_requests_total"] <= stage["max_requests"]:
            raise engine.EvaluationError("Model/batch limits exceed this campaign stage's allocation")
    with engine.run_lock(OUT):
        meta_path = OUT / "campaign.json"
        if meta_path.exists():
            if not resume or engine.read_json(meta_path).get("identity") != identity:
                raise engine.EvaluationError("Existing campaign requires unchanged identity and --resume")
        else:
            if resume:
                raise engine.EvaluationError("Cannot resume without campaign metadata")
            engine.write_json(meta_path, {"identity": identity, "state": "running", "started_at": engine.utc_now(), "authorized_max_requests": 1000})
        summary = {"state": "running", "stages": [], "accounting": request_accounting(campaign)}
        for stage in campaign["stages"]:
            output = engine.contained_path(ROOT, stage["output"])
            manifest = engine.contained_path(ROOT, stage["manifest"])
            if not (output / "batch.json").exists():
                snapshot(stage["name"], manifest)
            stage_result = eval_batch.run_batch(manifest, output, resume=(output / "batch.json").exists())
            summary["stages"].append({"name": stage["name"], "state": stage_result["state"]})
            summary["accounting"] = request_accounting(campaign)
            if stage["name"] == "precheck":
                try:
                    gate = precheck_gate(output) if stage_result.get("state") in {"complete", "complete_with_issues"} else {"passed": False}
                except (engine.EvaluationError, OSError, ValueError, KeyError, TypeError):
                    gate = {"passed": False, "reason": "Required precheck evidence is missing or invalid"}
                summary["precheck_gate"] = gate
                engine.write_json(OUT / "precheck_gate.json", gate)
                if not gate["passed"]:
                    summary["state"] = "stopped_precheck_failed"
                    break
            if stage_result.get("state") not in {"complete", "complete_with_issues"}:
                summary["state"] = "stage_failed"
                break
            engine.write_json(OUT / "campaign_summary.json", summary)
        if summary["state"] == "running":
            summary["state"] = "development_finished_pending_protocol_audit"
        summary["finished_at"] = engine.utc_now()
        summary["accounting"] = request_accounting(campaign)
        engine.write_json(OUT / "campaign_summary.json", summary)
        meta = engine.read_json(meta_path)
        meta.update(state=summary["state"], finished_at=summary["finished_at"])
        engine.write_json(meta_path, meta)
        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run", "status"])
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = prepare() if args.action == "prepare" else (run(resume=args.resume) if args.action == "run" else request_accounting(engine.read_json(CAMPAIGN)))
    print(json.dumps(result, ensure_ascii=False))
