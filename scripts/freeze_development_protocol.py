#!/usr/bin/env python3
"""Audit the authorized debug precheck and dev150 campaign; freeze only if clean."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import eval_engine as engine

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMPAIGN = "config/evaluation_campaign_1000.json"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
HTTP_ERROR_STATUSES = {400, 401, 402, 403, 404, 408, 413, 429, 500, 502, 503, 504}
EXPECTED_DEV_MODELS = {"deepseek-flash", "qwen3.8-flash", "glm-5.3-flash", "kimi-k3", "minimax-m3.1-flash", "doubao-seed-2.1-lite"}


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def read_jsonl(path: Path):
    try:
        with path.open(encoding="utf-8-sig") as stream:
            return [json.loads(line) for line in stream if line.strip()]
    except (OSError, ValueError):
        return None


def output_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def normalize_project_config(raw: dict) -> dict:
    """Normalize config paths relative to the repository, never the caller's cwd."""
    value = json.loads(json.dumps(raw))
    data_root = Path(value.get("data_root", "data/benchmark_web_v0.3"))
    if not data_root.is_absolute():
        value["data_root"] = str((ROOT / data_root).resolve())
    return engine.normalize_config(value)


def add_issue(issues: list[str], message: str) -> None:
    if message not in issues:
        issues.append(message)


def load_stage(spec: dict) -> dict:
    manifest_path = output_path(spec.get("manifest", ""))
    stage_manifest = read_json(manifest_path) or {}
    stage_dir = output_path(spec.get("output", ""))
    batch = read_json(stage_dir / "batch.json") or {}
    batch_summary = read_json(stage_dir / "batch_summary.json") or {}
    models = []
    for entry in stage_manifest.get("models", []):
        name = entry.get("output_name")
        run_dir = stage_dir / str(name)
        meta = read_json(run_dir / "run.json")
        preds = read_jsonl(run_dir / "predictions.jsonl")
        plan_rows = (batch.get("identity") or {}).get("models", [])
        plan = next((r for r in plan_rows if r.get("output_name") == name), {})
        declared_config_path = output_path(entry.get("config", ""))
        declared_config = read_json(declared_config_path)
        models.append({
            "entry": entry, "name": name, "run_dir": run_dir, "metadata": meta,
            "predictions": preds, "plan": plan, "config_path": declared_config_path,
            "declared_config": declared_config,
            "summary_row": next((r for r in (batch_summary.get("models") or []) if r.get("output_name") == name), {}),
        })
    return {"spec": spec, "manifest": stage_manifest, "manifest_path": manifest_path,
            "output": stage_dir, "batch": batch, "batch_summary": batch_summary, "models": models}


def data_snapshot(meta: dict) -> tuple[list[dict] | None, dict, list[str]]:
    issues = []
    cfg = meta.get("config") or {}
    root_value = cfg.get("data_root")
    if not root_value:
        return None, {}, ["config 缺少 data_root"]
    data_root = Path(root_value)
    if not data_root.is_absolute():
        data_root = ROOT / data_root
    manifest_path = data_root / "manifest.json"
    manifest = read_json(manifest_path)
    split = cfg.get("split")
    entry = ((manifest or {}).get("inputs") or {}).get(split, {})
    input_file = data_root / entry.get("path", "")
    rows = read_jsonl(input_file)
    ident = meta.get("identity") or {}
    if manifest is None or rows is None:
        issues.append("当前数据集 manifest 或输入 JSONL 缺失/不可读")
        return rows, {}, issues
    input_sha, manifest_sha = sha_file(input_file), sha_file(manifest_path)
    if input_sha != entry.get("sha256") or input_sha != ident.get("input_sha256"):
        issues.append("输入数据 SHA 与 manifest/run identity 不一致")
    if manifest_sha != ident.get("manifest_sha256"):
        issues.append("数据 manifest SHA 与 run identity 不一致")
    if split not in {"debug", "dev"}:
        issues.append(f"运行 split 应为 debug/dev，实际为 {split!r}")
    return rows, {"dataset_root": str(data_root), "split": split, "input_path": entry.get("path"),
                  "input_sha256": input_sha, "manifest_sha256": manifest_sha,
                  "ids": [r.get("id") for r in rows]}, issues


def detail_for(model: dict, prediction: dict) -> dict | None:
    name = Path(prediction.get("detail_path", "")).name
    if not name:
        return None
    return read_json(model["run_dir"] / "items" / name)


def summarize_reservations(meta: dict) -> dict:
    reservations = meta.get("remote_attempts")
    if not isinstance(reservations, list):
        return {"requests": None, "known_usage_requests": 0, "unknown_usage_requests": None,
                "total_tokens_known": None, "active_reserved": None, "interrupted_unknown": None,
                "budget_interrupted_or_inflight": None}
    known = [r.get("total_tokens") for r in reservations if isinstance(r.get("total_tokens"), int) and not isinstance(r.get("total_tokens"), bool)]
    return {"requests": len(reservations), "known_usage_requests": len(known),
            "unknown_usage_requests": len(reservations) - len(known),
            "total_tokens_known": sum(known) if known else None,
            "active_reserved": sum(r.get("state") == "reserved" for r in reservations),
            "interrupted_unknown": sum(r.get("state") == "interrupted_unknown" for r in reservations),
            "budget_interrupted_or_inflight": sum(r.get("state") in {"reserved", "interrupted_unknown"} for r in reservations)}


def budget_metadata_issues(meta: dict, reservation_summary: dict) -> list[str]:
    usage = meta.get("budget_usage")
    if not isinstance(usage, dict):
        return ["budget_usage缺失"]
    expected = {
        "remote_request_count": reservation_summary["requests"],
        "known_usage_request_count": reservation_summary["known_usage_requests"],
        "unknown_usage_request_count": reservation_summary["unknown_usage_requests"],
        "observed_total_tokens": reservation_summary["total_tokens_known"] or 0,
        "token_usage_complete": reservation_summary["unknown_usage_requests"] == 0,
        "interrupted_or_inflight_request_count": reservation_summary["budget_interrupted_or_inflight"],
    }
    return [f"budget_usage.{key} 与 remote_attempts不一致" for key, value in expected.items() if usage.get(key) != value]


def request_total(models: list[dict]) -> int | None:
    values = []
    for model in models:
        reservations = (model.get("metadata") or {}).get("remote_attempts")
        if not isinstance(reservations, list):
            return None
        values.append(len(reservations))
    return sum(values) if values else None


def checkpoint_reservations(path: Path) -> tuple[set[str], dict[str, dict], dict]:
    data = read_json(path)
    ids: set[str] = set()
    if not isinstance(data, dict):
        return ids, {}, {"available": False, "path": str(path)}
    records: dict[str, dict] = {}
    def visit(value):
        if isinstance(value, dict):
            rid = value.get("reservation_id")
            if isinstance(rid, str) and value.get("state") in {None, "reserved", "interrupted_unknown"}:
                ids.add(rid)
                records[rid] = value
            for key, child in value.items():
                if key.lower() in {"reserved_request_ids", "reservation_ids", "interrupted_reservation_ids"} and isinstance(child, list):
                    ids.update(x for x in child if isinstance(x, str))
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(data)
    accounting = data.get("accounting") if isinstance(data.get("accounting"), dict) else {}
    declared_count = next((accounting.get(k) for k in ("new_requests", "request_count", "remote_request_count", "total_requests") if isinstance(accounting.get(k), int)), None)
    if declared_count is None:
        declared_count = next((data.get(k) for k in ("request_count", "remote_request_count", "total_requests", "requests_at_checkpoint") if isinstance(data.get(k), int)), None)
    return ids, records, {"available": True, "path": str(path), "interrupted_reservation_count": len(ids),
                          "checkpoint_total_requests": declared_count}


def engine_snapshot_versions(stage: dict, metadata: dict) -> tuple[dict, list[str]]:
    """Verify the original engine and any IO-only resume engines against snapshots."""
    issues = []
    original = metadata.get("engine_sha256")
    resume_rows = metadata.get("resume_implementations", [])
    resume_hashes = []
    def collect(value):
        if isinstance(value, str) and SHA_RE.fullmatch(value):
            resume_hashes.append(value)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, dict):
            for key, child in value.items():
                if "sha256" in key.lower() or key.lower() in {"hash", "engine_hash"}:
                    collect(child)
    collect(resume_rows)
    index_path = stage["output"].parent / "implementation" / "implementation_index.json"
    index = read_json(index_path)
    if not isinstance(index, dict):
        issues.append("implementation_index缺失，不能验证阶段源码快照")
        return ({"original_engine_sha256": original, "resume_engine_sha256": sorted(set(resume_hashes)),
                 "snapshot_status": "missing_index"}, issues)
    stage_entries = ((index.get("stages") or {}).get(stage["spec"].get("name")) or [])
    found = []
    for item in stage_entries:
        directory = output_path(item.get("directory", ""))
        manifest_path = directory / "snapshot_manifest.json"
        snapshot = read_json(manifest_path)
        if not isinstance(snapshot, dict):
            issues.append(f"implementation snapshot缺失: {item.get('directory')}")
            continue
        snapshot_files = snapshot.get("files", [])
        all_files_valid = True
        for file_row in snapshot_files if isinstance(snapshot_files, list) else []:
            rel = file_row.get("path") if isinstance(file_row, dict) else None
            expected_file_hash = file_row.get("sha256") or file_row.get("hash") if isinstance(file_row, dict) else None
            try:
                actual_file = (directory / rel).resolve() if isinstance(rel, str) else None
                if (actual_file is None or not actual_file.is_relative_to(directory.resolve()) or
                        not actual_file.is_file() or sha_file(actual_file) != expected_file_hash):
                    all_files_valid = False
                    issues.append(f"snapshot文件缺失或SHA不符: {item.get('directory')}:{rel}")
            except (OSError, ValueError):
                all_files_valid = False
                issues.append(f"snapshot文件清单无效: {item.get('directory')}:{rel}")
        if not isinstance(snapshot_files, list) or not snapshot_files:
            all_files_valid = False
            issues.append(f"snapshot文件清单为空: {item.get('directory')}")
        engine_row = next((f for f in snapshot_files if isinstance(f, dict) and
                           (f.get("path", "").replace("\\", "/").endswith("scripts/eval_engine.py") or
                            Path(f.get("path", "")).name == "eval_engine.py")), None)
        expected_hash = (engine_row or {}).get("sha256") or (engine_row or {}).get("hash")
        if not isinstance(expected_hash, str) or not SHA_RE.fullmatch(expected_hash):
            issues.append(f"snapshot未声明eval_engine.py SHA: {item.get('directory')}")
            continue
        actual_path = directory / (engine_row.get("path") or "scripts/eval_engine.py")
        if not all_files_valid or not actual_path.is_file() or sha_file(actual_path) != expected_hash:
            issues.append(f"snapshot中的eval_engine.py文件与SHA不符: {item.get('directory')}")
            continue
        found.append({"directory": item.get("directory"), "scope": item.get("scope"),
                      "engine_sha256": expected_hash})
    initial = next((r for r in found if r.get("scope") == "initial"), found[0] if len(found) == 1 else None)
    available_resume = {
        r["engine_sha256"] for r in found if r is not initial
        and "candidate" not in str(r.get("scope", "")).lower()
        and str(r.get("directory", "")).replace("\\", "/").lower().endswith("_io_retry_v3")
    }
    allowed_run_start_hashes = available_resume | ({initial["engine_sha256"]} if initial else set())
    if original not in allowed_run_start_hashes:
        issues.append("run engine_sha256不匹配阶段initial/实际v3快照（v2候选不允许）")
    missing_resume = sorted(set(resume_hashes) - available_resume)
    if missing_resume:
        issues.append("resume_implementations SHA不在对应阶段追加快照中")
    return ({"original_engine_sha256": original,
             "resume_engine_sha256": sorted(set(resume_hashes)),
             "verified_snapshots": found,
             "snapshot_status": "verified" if found else "missing"}, issues)


def attempt_diagnostics(details: list[dict]) -> dict:
    http_errors: Counter = Counter()
    attempt_statuses: Counter = Counter()
    operational: Counter = Counter()
    observed: Counter = Counter()
    received = 0
    empty = 0
    length = 0
    reservation_ids = []
    historical_errors = Counter()
    for detail in details:
        for attempt in detail.get("attempts", []) if isinstance(detail.get("attempts"), list) else []:
            status = attempt.get("status", "unknown")
            attempt_statuses[status] += 1
            reservation_id = attempt.get("budget_reservation_id")
            if reservation_id:
                reservation_ids.append((detail.get("id"), reservation_id))
            if status != "received":
                historical_errors[status] += 1
            raw_status = attempt.get("http_status")
            if isinstance(raw_status, int) and (raw_status >= 400 or raw_status in HTTP_ERROR_STATUSES):
                http_errors[str(raw_status)] += 1
            if status == "received":
                received += 1
                raw = attempt.get("raw_response")
                choices = raw.get("choices", []) if isinstance(raw, dict) else []
                if choices and isinstance(choices[0], dict):
                    choice = choices[0]
                    if choice.get("finish_reason") == "length":
                        length += 1
                        observed["finish_reason_length"] += 1
                    msg = choice.get("message")
                    content = msg.get("content") if isinstance(msg, dict) else None
                    if content is None or (isinstance(content, str) and not content.strip()):
                        empty += 1
                        observed["empty_response"] += 1
                    if isinstance(msg, dict) and msg.get("refusal"):
                        observed["refusal"] += 1
                else:
                    operational["invalid_response"] += 1
    return {"http_errors": dict(http_errors), "attempt_statuses": dict(attempt_statuses),
            "operational_blockers": dict(operational), "observed_model_failures": dict(observed), "received": received,
            "reservation_ids": reservation_ids, "historical_errors": dict(historical_errors),
            "empty_responses": empty, "finish_reason_length": length}


def final_received_is_length(detail: dict | None) -> bool:
    if not isinstance(detail, dict):
        return False
    received = []
    for attempt in detail.get("attempts", []):
        if isinstance(attempt, dict) and attempt.get("status") == "received":
            received.append(attempt)
    if not received:
        return False
    raw = received[-1].get("raw_response")
    choices = raw.get("choices", []) if isinstance(raw, dict) else []
    return bool(choices and isinstance(choices[0], dict) and choices[0].get("finish_reason") == "length")


def prediction_detail_issues(prediction: dict, detail: dict, run_id: str) -> list[str]:
    issues = []
    if engine.summary_record(detail) != prediction:
        issues.append("prediction记录与item detail摘要不一致")
    if detail.get("id") != prediction.get("id") or detail.get("run_id") != run_id:
        issues.append("item detail ID/run_id不匹配")
    attempts = detail.get("attempts", [])
    final = attempts[-1] if attempts else None
    if isinstance(final, dict) and final.get("status") == "received":
        try:
            content, refusal, _usage = engine.extract_response(final.get("raw_response"))
            parsed = engine.parse_answer(content, refusal)
            if parsed.get("status") != detail.get("status") or parsed.get("answer") != detail.get("answer"):
                issues.append("最终journal答案与received raw response解析不一致")
            if detail.get("response_text") != content:
                issues.append("response_text与received raw response不一致")
        except Exception:
            issues.append("最终received raw response结构无效")
    return issues


def padding_evidence_passes(detail: dict | None) -> bool:
    if not isinstance(detail, dict):
        return False
    evidence = detail.get("image_processing")
    if not isinstance(evidence, list):
        return False
    # The unchanged 157x139 geometry figure is recorded alongside the four
    # tiny option images. Only the latter belong to this padding check.
    small_images = [row for row in evidence if isinstance(row, dict) and row.get("source_dimensions") == [8, 35]]
    if len(small_images) != 4:
        return False
    return all(
        isinstance(row, dict)
        and
        row.get("source_dimensions") == [8, 35]
        and row.get("derived_dimensions") == [32, 35]
        and isinstance(row.get("source_sha256"), str) and SHA_RE.fullmatch(row["source_sha256"])
        and isinstance(row.get("derived_sha256"), str) and SHA_RE.fullmatch(row["derived_sha256"])
        and row["source_sha256"] != row["derived_sha256"]
        for row in small_images
    )


def validate_pre_model(stage: dict, model: dict, checkpoint_records: dict[str, dict]) -> list[str]:
    issues = []
    meta, rows = model.get("metadata"), model.get("predictions")
    if not isinstance(meta, dict) or not isinstance(rows, list):
        return ["precheck运行日志缺失"]
    cfg, ident = meta.get("config") or {}, meta.get("identity") or {}
    declared = model.get("declared_config")
    try:
        normalized = normalize_project_config(declared) if isinstance(declared, dict) else None
    except Exception:
        normalized = None
    if normalized is None or normalized != cfg or sha_json(normalized) != ident.get("config_sha256"):
        issues.append("precheck声明config或config SHA不匹配")
    if cfg.get("split") != "debug":
        issues.append("precheck必须严格使用debug split")
    if meta.get("synthetic") is not False or any(r.get("synthetic") is not False for r in rows):
        issues.append("precheck不是明确的真实模型运行")
    if meta.get("state") not in {"complete", "complete_with_issues", "budget_exhausted"}:
        issues.append("precheck run未完成")
    _, version_issues = engine_snapshot_versions(stage, meta)
    issues.extend(version_issues)
    if model["summary_row"].get("state") not in {"complete", "complete_with_issues"}:
        issues.append("precheck模型batch日志未完成")
    if model["plan"].get("config_sha256") != ident.get("config_sha256"):
        issues.append("precheck batch plan config SHA不匹配")
    if (stage["batch"].get("identity") or {}).get("batch_manifest_sha256") != sha_file(stage["manifest_path"]):
        issues.append("precheck batch manifest SHA与运行manifest不匹配")
    snapshot_rows, snap, data_issues = data_snapshot(meta)
    issues.extend(data_issues)
    if snap:
        if snap.get("split") != "debug":
            issues.append("precheck数据快照不是debug")
        pinned = stage["manifest"].get("expected_data_manifest_sha256")
        if pinned and snap["manifest_sha256"] != pinned:
            issues.append("precheck当前manifest与stage pin不匹配")
        plan_data = model["plan"].get("dataset") or {}
        if (plan_data.get("dataset_root") != snap["dataset_root"] or
                plan_data.get("input_path") != snap["input_path"] or
                plan_data.get("input_sha256") != snap["input_sha256"] or
                plan_data.get("manifest_sha256") != snap["manifest_sha256"]):
            issues.append("precheck batch plan数据路径/hash与当前数据不匹配")
        if snapshot_rows is not None:
            order_hash = sha_json([q["id"] for q in engine.prioritize_items(snapshot_rows, normalize_project_config(cfg))])
            if model["plan"].get("input_order_sha256") != order_hash:
                issues.append("precheck batch plan input order SHA不匹配")
    if (meta.get("prompt_version") != engine.PROMPT_VERSION or meta.get("system_prompt") != engine.SYSTEM_PROMPT or
            sha_json({"version": meta.get("prompt_version"), "system_prompt": meta.get("system_prompt")}) != ident.get("prompt_sha256") or
            (stage["batch"].get("identity") or {}).get("prompt_sha256") != ident.get("prompt_sha256")):
        issues.append("precheck batch/run prompt pins不匹配")
    reservations = meta.get("remote_attempts")
    if not isinstance(reservations, list):
        issues.append("precheck remote_attempts缺失")
        reservations = []
    elif any(r.get("state") == "reserved" for r in reservations):
        issues.append("precheck存在inflight reservation")
    pre_reservation_summary = summarize_reservations(meta)
    issues.extend(budget_metadata_issues(meta, pre_reservation_summary))
    if len(reservations) > stage["spec"].get("max_requests", 8) or (
            isinstance(cfg.get("max_requests"), int) and len(reservations) > cfg["max_requests"]):
        issues.append("precheck请求数超过stage/model cap")
    reservation_map = {r.get("reservation_id"): r.get("item_id") for r in reservations if isinstance(r, dict)}
    attempts = []
    for pred in rows:
        if pred.get("run_id") != meta.get("run_id"):
            issues.append("precheck prediction run_id不匹配")
        if pred.get("attempted") is not True:
            continue
        detail = detail_for(model, pred)
        if not isinstance(detail, dict) or not detail.get("complete") or detail.get("id") != pred.get("id") or detail.get("run_id") != meta.get("run_id"):
            issues.append("precheck attempted item detail缺失/不匹配")
            continue
        issues.extend(prediction_detail_issues(pred, detail, meta.get("run_id")))
        item_attempts = detail.get("attempts", [])
        if not item_attempts:
            issues.append("precheck attempted item没有attempt记录")
        attempts.extend((pred.get("id"), a.get("budget_reservation_id")) for a in item_attempts if isinstance(a, dict))
    attempted_ids = {rid for _, rid in attempts}
    orphan_rows = [r for r in reservations if r.get("reservation_id") not in attempted_ids]
    allowed_orphans = set()
    for reservation in orphan_rows:
        rid = reservation.get("reservation_id")
        checkpoint_row = checkpoint_records.get(rid, {})
        matches = (checkpoint_row.get("stage") == stage["spec"].get("name") and
                   checkpoint_row.get("model") == model["name"] and
                   checkpoint_row.get("item_id") == reservation.get("item_id"))
        if reservation.get("state") == "interrupted_unknown" and matches and reservation.get("total_tokens") is None:
            allowed_orphans.add(rid)
    if (len(reservation_map) != len(reservations) or len({rid for _, rid in attempts}) != len(attempts) or
            any(reservation_map.get(rid) != item_id for item_id, rid in attempts) or
            len(allowed_orphans) != len(orphan_rows)):
        issues.append("precheck remote reservation与attempt不能一一对账")
    return issues


def audit_model(stage: dict, model: dict, expected_ids: list[str] | None,
                stage_cap: int, per_model_cap: int | None, checkpoint_records: dict[str, dict]) -> dict:
    issues: list[str] = []
    name, meta, rows = model["name"], model["metadata"], model["predictions"]
    if not isinstance(meta, dict):
        return {"output_name": name, "state": "missing", "qualified_complete": False,
                "issues": ["run.json 缺失"], "requests": None}
    if not isinstance(rows, list):
        rows = []
        add_issue(issues, "predictions.jsonl 缺失/不可读")
    cfg, ident = meta.get("config") or {}, meta.get("identity") or {}
    declared = model.get("declared_config")
    if not isinstance(declared, dict):
        add_issue(issues, "声明配置缺失/不可读")
    else:
        try:
            normalized_declared = normalize_project_config(declared)
            if sha_json(normalized_declared) != ident.get("config_sha256"):
                add_issue(issues, "config SHA 与 run identity 不匹配")
            if cfg != normalized_declared:
                add_issue(issues, "run config 与声明配置不一致")
        except Exception:
            add_issue(issues, "声明配置格式无效")
    if model["plan"].get("config_sha256") and model["plan"].get("config_sha256") != ident.get("config_sha256"):
        add_issue(issues, "batch plan config SHA 与 run identity 不匹配")
    if meta.get("synthetic") is not False or any(r.get("synthetic") is not False for r in rows):
        add_issue(issues, "结果标记为 synthetic 或缺少真实运行标记")
    if meta.get("state") not in {"complete", "complete_with_issues"}:
        add_issue(issues, f"run 未正常结束（state={meta.get('state', 'missing')}）")
    if model["summary_row"].get("state") not in {"complete", "complete_with_issues"}:
        add_issue(issues, f"batch model 未正常结束（state={model['summary_row'].get('state', 'missing')}）")
    counts = Counter(r.get("id") for r in rows)
    duplicate_ids = [identifier for identifier, count in counts.items() if count > 1]
    if duplicate_ids:
        add_issue(issues, f"prediction ID 重复 {len(duplicate_ids)} 条")
    if expected_ids is not None and set(counts) != set(expected_ids):
        add_issue(issues, f"prediction 覆盖不匹配：missing={len(set(expected_ids)-set(counts))}, extra={len(set(counts)-set(expected_ids))}")
    details = []
    status_counts = Counter(r.get("status", "missing") for r in rows)
    for prediction in rows:
        if prediction.get("run_id") != meta.get("run_id"):
            add_issue(issues, "prediction run_id 与 run.json 不匹配")
        if prediction.get("status") == "ok" and prediction.get("answer") not in {"A", "B", "C", "D"}:
            add_issue(issues, "ok prediction 缺少合法A-D答案")
        detail = detail_for(model, prediction)
        if detail is None or not detail.get("complete"):
            add_issue(issues, "至少一条 item detail 缺失或未完成")
            continue
        for pair_issue in prediction_detail_issues(prediction, detail, meta.get("run_id")):
            add_issue(issues, pair_issue)
        if prediction.get("attempted") is True:
            attempts = detail.get("attempts", [])
            if not attempts:
                add_issue(issues, "attempted prediction没有持久化attempt")
            elif attempts[-1].get("status") != "received":
                add_issue(issues, "存在未恢复的最终API/transport/timeout失败")
        details.append(detail)
    diagnostics = attempt_diagnostics(details)
    if expected_ids is not None and (len(rows) != len(expected_ids) or len(counts) != len(expected_ids)):
        add_issue(issues, f"预测记录数应为 {len(expected_ids)}，实际 {len(rows)}")
    if len(rows) != len(expected_ids or rows) or any(r.get("attempted") is not True for r in rows):
        add_issue(issues, "并非所有 dev 输入都有实际attempted结果")
    observed_failures = Counter(diagnostics["observed_model_failures"])
    observed_failure_ids = set()
    for record in rows:
        status = record.get("status")
        if status == "parse_failure":
            observed_failures["parse_failure"] += 1
            observed_failure_ids.add(record.get("id"))
        elif status == "refusal":
            observed_failures["refusal"] += 1
            observed_failure_ids.add(record.get("id"))
        elif status not in {"ok", "parse_failure", "refusal"}:
            add_issue(issues, f"存在运行结果状态 {status!r}（缺图、未运行或其他运行阻断）")
        detail = detail_for(model, record) or {}
        for attempt in detail.get("attempts", []):
            raw = attempt.get("raw_response") if isinstance(attempt, dict) else None
            choices = raw.get("choices", []) if isinstance(raw, dict) else []
            if choices and isinstance(choices[0], dict):
                choice = choices[0]
                message = choice.get("message") or {}
                message = message if isinstance(message, dict) else {}
                content = message.get("content")
                if (choice.get("finish_reason") == "length" or message.get("refusal") or
                        content is None or (isinstance(content, str) and not content.strip())):
                    observed_failure_ids.add(record.get("id"))
    reservation = summarize_reservations(meta)
    issues.extend(budget_metadata_issues(meta, reservation))
    if reservation["requests"] is None:
        add_issue(issues, "remote_attempts 缺失，不能核实请求数")
    else:
        if reservation["requests"] > stage_cap:
            add_issue(issues, f"超过 stage 请求上限 {stage_cap}")
        if per_model_cap is not None and reservation["requests"] > per_model_cap:
            add_issue(issues, f"超过单模型请求上限 {per_model_cap}")
        if reservation["active_reserved"]:
            add_issue(issues, "存在仍处于reserved状态的请求")
        remote = meta.get("remote_attempts", [])
        reservation_map = {r.get("reservation_id"): r.get("item_id") for r in remote if isinstance(r, dict)}
        attempt_pairs = diagnostics["reservation_ids"]
        attempt_ids = {rid for _, rid in attempt_pairs}
        orphan_rows = [r for r in remote if r.get("reservation_id") not in attempt_ids]
        allowed_orphans = set()
        for reservation_row in orphan_rows:
            rid = reservation_row.get("reservation_id")
            checkpoint_row = checkpoint_records.get(rid, {})
            matches = (checkpoint_row.get("stage") == stage["spec"].get("name") and
                       checkpoint_row.get("model") == name and
                       checkpoint_row.get("item_id") == reservation_row.get("item_id"))
            if reservation_row.get("state") == "interrupted_unknown" and matches and reservation_row.get("total_tokens") is None:
                allowed_orphans.add(rid)
        if (len(reservation_map) != reservation["requests"] or len({rid for _, rid in attempt_pairs}) != len(attempt_pairs) or
                len(allowed_orphans) != len(orphan_rows)):
            add_issue(issues, "reservation 与 item attempt 无法一一核对")
        elif any(reservation_map.get(rid) != item_id for item_id, rid in attempt_pairs):
            add_issue(issues, "remote_attempt reservation_id/item_id 与 item attempt 不匹配")
    identity_ok = bool(ident.get("input_sha256") and ident.get("manifest_sha256") and
                       ident.get("prompt_sha256") and ident.get("config_sha256"))
    if not identity_ok:
        add_issue(issues, "run identity 的数据/manifest/prompt/config SHA 不完整")
    interval = None
    if name == "kimi-k3":
        times = []
        for r in meta.get("remote_attempts", []) if isinstance(meta.get("remote_attempts"), list) else []:
            try:
                times.append(datetime.fromisoformat(r["started_at"].replace("Z", "+00:00")).timestamp())
            except (KeyError, TypeError, ValueError):
                pass
        gaps = [b-a for a, b in zip(sorted(times), sorted(times)[1:])]
        interval = min(gaps) if gaps else None
        if interval is None or interval < 20.9:
            add_issue(issues, "Kimi 实际请求间隔不足 20.9 秒或缺少时间戳")
    score = read_json(model["run_dir"] / "score.json")
    if not isinstance(score, dict):
        add_issue(issues, "score.json 缺失或不可读")
        score = {}
    rechecked_score = None
    recheck_path = stage["output"].parent / "reports" / "rechecked_scores" / f"{name}.json"
    try:
        rechecked_score = engine.score_run(model["run_dir"], recheck_path)
    except Exception:
        add_issue(issues, "离线score重算失败（data/answers/prediction-detail一致性未通过）")
    if isinstance(rechecked_score, dict) and isinstance(score, dict):
        stable_score_keys = ("schema_version", "run_id", "synthetic", "result_kind", "identity", "run_state",
                             "budget_usage", "budget_limits", "answer_tables", "overall", "groups", "pairs",
                             "pairs_by_split", "metric_definitions")
        if any(score.get(key) != rechecked_score.get(key) for key in stable_score_keys):
            add_issue(issues, "score.json与从当前answers/predictions离线重算结果不一致")
    if score.get("run_id") != meta.get("run_id") or score.get("synthetic") != meta.get("synthetic"):
        add_issue(issues, "score run_id/synthetic 与 run.json 不匹配")
    if score.get("run_state") != meta.get("state"):
        add_issue(issues, "score run_state 与 run.json 不匹配")
    if score.get("identity") != ident:
        add_issue(issues, "score identity 与 run identity 不匹配")
    overall = score.get("overall") if isinstance(score.get("overall"), dict) else {}
    parsed_actual = sum(r.get("status") == "ok" and r.get("answer") in {"A", "B", "C", "D"} for r in rows)
    metric_ints = all(type(overall.get(k)) is int for k in ("total", "recorded", "attempted", "parsed", "correct"))
    expected_accuracy = (overall["correct"] / overall["attempted"]
                         if type(overall.get("correct")) is int and type(overall.get("attempted")) is int and overall["attempted"] else None)
    if (overall.get("total") != len(expected_ids or rows) or overall.get("recorded") != len(rows) or
            overall.get("attempted") != len(expected_ids or rows) or overall.get("parsed") != parsed_actual):
        add_issue(issues, "score overall total/recorded/attempted/parsed 与 dev predictions 不符")
    if (not metric_ints or overall["correct"] < 0 or overall["correct"] > overall["attempted"] or
            overall.get("accuracy") != expected_accuracy):
        add_issue(issues, "score correct/accuracy 分母或范围不一致")
    expected_among_parsed = overall.get("correct") / parsed_actual if type(overall.get("correct")) is int and parsed_actual else None
    expected_coverage = parsed_actual / len(expected_ids or rows) if (expected_ids or rows) else None
    if overall.get("accuracy_among_parsed") != expected_among_parsed or overall.get("answer_coverage") != expected_coverage:
        add_issue(issues, "score parsed准确率/coverage 与 predictions 不一致")
    if overall.get("status_counts") != dict(status_counts):
        add_issue(issues, "score status_counts 与 predictions 不一致")
    final_status = {r.get("id"): r.get("status") for r in rows}
    recovered_errors: Counter = Counter()
    for detail in details:
        if final_status.get(detail.get("id")) != "ok":
            continue
        for attempt in detail.get("attempts", []):
            if attempt.get("status") != "received":
                recovered_errors[attempt.get("status", "unknown")] += 1
            http_status = attempt.get("http_status")
            if isinstance(http_status, int) and http_status >= 400:
                recovered_errors[f"HTTP_{http_status}"] += 1
    return {
        "output_name": name, "model": cfg.get("backend", {}).get("model"),
        "state": meta.get("state"), "operationally_complete": not issues,
        "qualified_for_development": not issues,
        "issues": issues, "status_counts": dict(status_counts), "requests": reservation["requests"],
        "tokens": {k: reservation[k] for k in ("total_tokens_known", "known_usage_requests", "unknown_usage_requests")},
        "http_error_groups": diagnostics["http_errors"], "attempt_status_groups": diagnostics["attempt_statuses"],
        "operational_blocker_groups": diagnostics["operational_blockers"],
        "historical_attempt_errors": diagnostics["historical_errors"],
        "recovered_errors": dict(recovered_errors),
        "unresolved_final_operational_failures": dict(Counter(r.get("status") for r in rows if r.get("status") not in {"ok", "parse_failure", "refusal"})),
        "observed_model_failures": dict(observed_failures),
        "observed_failure_question_count": len(observed_failure_ids),
        "finish_reason_length": diagnostics["finish_reason_length"],
        "minimum_request_interval_seconds": interval,
        "correct": overall.get("correct"), "attempted": overall.get("attempted"),
        "accuracy_correct_over_attempted_dev_only": overall.get("accuracy"),
        "accuracy_among_parsed_dev_only": overall.get("accuracy_among_parsed"),
        "answer_coverage_dev_only": overall.get("answer_coverage"),
        "identity": {k: ident.get(k) for k in ("config_sha256", "input_sha256", "manifest_sha256", "prompt_sha256", "split")},
        "score_recheck_path": str(recheck_path),
        "config": cfg,
    }


def compare_and_audit(campaign: dict, stages: list[dict]) -> dict:
    issues: list[str] = []
    specs = {s["spec"].get("name"): s for s in stages}
    pre, dev = specs.get("precheck"), specs.get("development")
    if pre is None or dev is None:
        return {"state": "candidate_with_issues", "issues": ["campaign 缺少 precheck/development stage"]}
    if not pre["batch"] or not dev["batch"]:
        return {"state": "interim", "issues": ["一个或多个 batch.json 尚未创建；暂不写冻结文件"], "reports": []}
    checkpoint_path = ROOT / "runs/campaign_1000/io_interruption_checkpoint.json"
    checkpoint_ids, checkpoint_records, checkpoint_info = checkpoint_reservations(checkpoint_path)
    if checkpoint_info["available"] and (checkpoint_info.get("checkpoint_total_requests") != 275 or len(checkpoint_ids) != 3):
        add_issue(issues, "IO中断checkpoint应可证明275个既有请求与3个pending reservation")
    campaign_cap = next((campaign.get(k) for k in ("authorized_new_request_cap", "authorized_max_requests", "max_requests_total", "request_cap") if campaign.get(k) is not None), None)
    if campaign_cap != 1000:
        add_issue(issues, "campaign 授权总上限未明确为1000")
    if pre["spec"].get("max_requests") != 8 or dev["spec"].get("max_requests") != 990:
        add_issue(issues, "stage cap 应为 precheck=8、development=990")
    ended_states = {"complete", "complete_with_issues"}
    if pre["batch"].get("state") not in ended_states or dev["batch"].get("state") not in ended_states:
        add_issue(issues, "至少一个 batch 尚未 complete")
    if pre["batch_summary"].get("state") not in ended_states or dev["batch_summary"].get("state") not in ended_states:
        add_issue(issues, "至少一个 batch_summary 尚未 complete")
    pre_results = []
    if {m["name"] for m in pre["models"]} != {"qwen3.8-flash", "minimax-m3.1-flash"}:
        add_issue(issues, "precheck必须且只能包含Qwen和MiniMax两家")
    for model in pre["models"]:
        model_pre_issues = validate_pre_model(pre, model, checkpoint_records)
        if not model["metadata"] or model["predictions"] is None:
            pre_results.append({"output_name": model["name"], "issues": model_pre_issues or ["运行日志缺失"], "qualified_complete": False})
            continue
        rows = model["predictions"]
        by_id = {r.get("id"): r for r in rows}
        if model["name"] == "qwen3.8-flash":
            row = by_id.get("EMB-P-WEB2-TIKU-1754090", {})
            detail = detail_for(model, row) if row else None
            has_received = bool(detail and any(a.get("status") == "received" for a in detail.get("attempts", []) if isinstance(a, dict)))
            good = (not model_pre_issues and row.get("status") == "ok" and has_received and not final_received_is_length(detail)
                    and padding_evidence_passes(detail)
                    and bool(detail and detail.get("complete"))
                    and model["metadata"].get("synthetic") is False)
            pre_results.append({"output_name": model["name"], "qualified_complete": good,
                                "requests": summarize_reservations(model["metadata"])["requests"],
                                "problem_status": row.get("status", "missing"),
                                "issues": [] if good else model_pre_issues + ["Qwen 问题题未取得非截断且4张图有8x35->32x35 padding证据的最终ok结果"]})
        elif model["name"] == "minimax-m3.1-flash":
            rows_input, _, _ = data_snapshot(model["metadata"])
            image_ids = {r.get("id") for r in rows_input or [] if r.get("image_assets")}
            good_ids = []
            for identifier in image_ids:
                prediction = by_id.get(identifier, {})
                detail = detail_for(model, prediction) if prediction else None
                if (prediction.get("status") == "ok" and detail and detail.get("complete") and
                        any(a.get("status") == "received" for a in detail.get("attempts", []) if isinstance(a, dict))):
                    good_ids.append(identifier)
            good = not model_pre_issues and bool(good_ids) and model["metadata"].get("synthetic") is False
            pre_results.append({"output_name": model["name"], "qualified_complete": good,
                                "requests": summarize_reservations(model["metadata"])["requests"],
                                "successful_image_questions": len(good_ids),
                                "issues": [] if good else model_pre_issues + ["MiniMax precheck 没有至少一条实际received图题ok"]})
    for model in pre["models"]:
        reservations = summarize_reservations(model.get("metadata") or {})
        per_cap = ((model.get("declared_config") or {}).get("max_requests"))
        if reservations["requests"] is None:
            add_issue(issues, f"precheck {model['name']}: remote_attempts 缺失")
        elif reservations["requests"] > pre["spec"].get("max_requests", 8) or (per_cap is not None and reservations["requests"] > per_cap):
            add_issue(issues, f"precheck {model['name']}: 请求数超 stage/per-model cap")
    if len(pre_results) != 2 or not all(r.get("qualified_complete") for r in pre_results):
        add_issue(issues, "step1 两模补验未全部通过")
    dev_models = dev["models"]
    if len(dev_models) != 6:
        add_issue(issues, f"development 应有6个模型，实际 {len(dev_models)}")
    if {m.get("name") for m in dev_models} != EXPECTED_DEV_MODELS:
        add_issue(issues, "development 模型集合与当前六家名单不一致")
    snapshots, declared_prompt_version, declared_sys_prompt = [], None, None
    input_order_hashes = set()
    dev_results = []
    expected_ids = None
    for model in dev_models:
        meta = model["metadata"] or {}
        if (dev["batch"].get("identity") or {}).get("batch_manifest_sha256") != sha_file(dev["manifest_path"]):
            add_issue(issues, "development batch manifest SHA与运行manifest不匹配")
        if meta:
            source_versions, source_issues = engine_snapshot_versions(dev, meta)
        else:
            source_versions, source_issues = {}, ["run metadata缺失，无法校验engine版本"]
        for issue in source_issues:
            add_issue(issues, f"{model['name']}: {issue}")
        rows, snap, data_issues = data_snapshot(meta)
        for issue in data_issues:
            add_issue(issues, f"{model['name']}: {issue}")
        if snap:
            snapshots.append(snap)
            if (dev["batch"].get("identity") or {}).get("batch_manifest_sha256") != sha_file(dev["manifest_path"]):
                add_issue(issues, "development batch manifest SHA与声明manifest不匹配")
            pinned_manifest = dev["manifest"].get("expected_data_manifest_sha256")
            if pinned_manifest and snap["manifest_sha256"] != pinned_manifest:
                add_issue(issues, f"{model['name']}: 当前 manifest SHA 与 stage pin 不一致")
            try:
                ordered_ids = [q["id"] for q in engine.prioritize_items(rows, normalize_project_config(meta["config"]))]
            except Exception:
                ordered_ids = snap["ids"]
                add_issue(issues, f"{model['name']}: 无法重建完整输入顺序")
            ids = ordered_ids
            order_hash = sha_json(ids)
            input_order_hashes.add(order_hash)
            if model["plan"].get("input_order_sha256") != order_hash:
                add_issue(issues, f"{model['name']}: 输入顺序 SHA 与 batch 声明不一致")
            plan_data = model["plan"].get("dataset") or {}
            if (plan_data.get("dataset_root") != snap["dataset_root"] or plan_data.get("input_path") != snap["input_path"] or
                    plan_data.get("input_sha256") != snap["input_sha256"] or plan_data.get("manifest_sha256") != snap["manifest_sha256"]):
                add_issue(issues, f"{model['name']}: batch plan 数据/manifest SHA 与当前数据不一致")
            if expected_ids is None:
                expected_ids = ids
            elif ids != expected_ids:
                add_issue(issues, f"{model['name']}: dev 输入 ID 顺序与其他模型不一致")
            if len(ids) != 150:
                add_issue(issues, f"{model['name']}: dev 输入应150条，实际{len(ids)}")
        cfg = meta.get("config") or {}
        backend = cfg.get("backend") or {}
        if cfg.get("max_requests") != 165:
            add_issue(issues, f"{model['name']}: 单模型 cap 应为165")
        if backend.get("max_output_tokens") != 8192:
            add_issue(issues, f"{model['name']}: 输出上限应为8192")
        if cfg.get("split") != "dev":
            add_issue(issues, f"{model['name']}: split 不是 dev")
        if backend.get("supports_images") is not True or backend.get("minimum_image_dimension") != 32:
            add_issue(issues, f"{model['name']}: 图片支持/padded32 设置不符")
        if backend.get("request_interval_seconds") != (21 if model["name"] == "kimi-k3" else 1):
            add_issue(issues, f"{model['name']}: 请求间隔配置不符")
        if declared_prompt_version is None:
            declared_prompt_version, declared_sys_prompt = meta.get("prompt_version"), meta.get("system_prompt")
        elif (meta.get("prompt_version"), meta.get("system_prompt")) != (declared_prompt_version, declared_sys_prompt):
            add_issue(issues, f"{model['name']}: system prompt/version 与同批模型不一致")
        prompt_digest = sha_json({"version": meta.get("prompt_version"), "system_prompt": meta.get("system_prompt")})
        if meta.get("prompt_version") != "emb-choice-v1":
            add_issue(issues, f"{model['name']}: prompt_version 应为 emb-choice-v1")
        if meta.get("prompt_version") != engine.PROMPT_VERSION or meta.get("system_prompt") != engine.SYSTEM_PROMPT:
            add_issue(issues, f"{model['name']}: prompt 与当前声明版本/正文不一致")
        if prompt_digest != (meta.get("identity") or {}).get("prompt_sha256"):
            add_issue(issues, f"{model['name']}: prompt SHA 不一致")
        if (dev["batch"].get("identity") or {}).get("prompt_sha256") != (meta.get("identity") or {}).get("prompt_sha256"):
            add_issue(issues, f"{model['name']}: batch/run prompt pin不匹配")
        limit = next((r.get("max_requests") for r in dev["manifest"].get("models", []) if r.get("output_name") == model["name"]), 165)
        result = audit_model(dev, model, expected_ids, dev["spec"].get("max_requests", 990), limit, checkpoint_records)
        result["source_versions"] = source_versions
        dev_results.append(result)
        for issue in result["issues"]:
            add_issue(issues, f"{model['name']}: {issue}")
    if snapshots and len({(s["input_sha256"], s["manifest_sha256"], tuple(s["ids"])) for s in snapshots}) > 1:
        add_issue(issues, "模型间 data/input SHA 或完整 ID 顺序不一致")
    if len(input_order_hashes) > 1:
        add_issue(issues, "六模 full input order 不一致")
    pre_total = request_total(pre["models"])
    dev_total = request_total(dev["models"])
    requests_complete = isinstance(pre_total, int) and isinstance(dev_total, int)
    total = pre_total + dev_total if requests_complete else None
    if total is not None and total > 1000:
        add_issue(issues, f"新增请求总数 {total} 超过授权1000")
    if requests_complete and (pre_total > pre["spec"].get("max_requests", 8) or dev_total > dev["spec"].get("max_requests", 990)):
        add_issue(issues, "至少一个 stage 超出请求上限")
    for result in pre_results:
        if not result.get("qualified_complete"):
            add_issue(issues, f"precheck {result['output_name']}: {result['issues'][0]}")
    missing_logs = any(not m["metadata"] or m["predictions"] is None for s in stages for m in s["models"])
    if missing_logs:
        add_issue(issues, "存在缺失的运行日志")
    all_reservations = [r for s in stages for m in s["models"]
                        for r in ((m.get("metadata") or {}).get("remote_attempts") or []) if isinstance(r, dict)]
    interrupted_ids = {r.get("reservation_id") for r in all_reservations if r.get("state") == "interrupted_unknown"}
    if checkpoint_info["available"]:
        if interrupted_ids != checkpoint_ids:
            add_issue(issues, "checkpoint pending IDs与run中的interrupted_unknown IDs不一致")
    elif interrupted_ids:
        add_issue(issues, "存在interrupted_unknown reservation但缺少checkpoint凭据")
    all_run_models = [m for s in stages for m in s["models"]]
    pre_names = {m["name"] for m in pre["models"]}
    dev_names = {m["name"] for m in dev["models"]}
    formal_test_requests = 0 if (len(all_run_models) == 8 and
        pre_names == {"qwen3.8-flash", "minimax-m3.1-flash"} and dev_names == EXPECTED_DEV_MODELS and
        all(m.get("metadata") and m.get("predictions") is not None for m in all_run_models) and
        all((m["metadata"].get("config") or {}).get("split") == "debug" for m in pre["models"]) and
        all((m["metadata"].get("config") or {}).get("split") == "dev" for m in dev["models"])) else None
    if formal_test_requests is None:
        add_issue(issues, "无法证明campaign恰好为两条debug precheck和六条dev运行；formal_test_requests未知")
    for result in dev_results:
        observed = result.get("observed_model_failures", {})
        result["observed_failure_count"] = result.get("observed_failure_question_count", 0)
        denominator = result.get("attempted") or 0
        result["observed_failure_rate"] = result["observed_failure_count"] / denominator if denominator else None
    observed_any = any(r.get("observed_failure_count", 0) for r in dev_results)
    frozen = not issues and total is not None and all(r.get("operationally_complete") for r in dev_results)
    return {"state": ("frozen_with_observed_model_failures" if observed_any else "frozen") if frozen else ("interim" if any(s["batch"].get("state") == "running" for s in stages) or missing_logs else "candidate_with_issues"),
            "issues": issues, "precheck": pre_results, "development": dev_results,
            "precheck_source_versions": {m["name"]: engine_snapshot_versions(pre, m["metadata"])[0]
                                          for m in pre["models"] if isinstance(m.get("metadata"), dict)},
            "precheck_requests": pre_total if requests_complete else None,
            "development_requests": dev_total if requests_complete else None,
            "interruption_checkpoint": checkpoint_info,
            "new_campaign_requests": total, "previous_72_requests_separate": 72,
            "total_if_including_previous": total + 72 if total is not None else None,
            "authorization_cap": 1000, "stage_caps": {"precheck": 8, "development": 990},
            "per_model_cap": 165, "formal_test_requests": formal_test_requests,
            "accuracy_scope": "主准确率为 correct/attempted；accuracy_among_parsed 仅作辅助，answer_coverage 单列。dev150 仅用于开发，不是正式 test 成绩；本批全为原题，母题-变式指标不适用。",
            "datasets": snapshots, "prompt_version": declared_prompt_version,
            "system_prompt": declared_sys_prompt,
            "parameter_modes_by_model": {m["output_name"]: (m.get("config") or {}).get("parameter_mode") for m in dev_results},
            "mode_note": "六家各自保留已声明的 backend/request_extra 参数模式；本协议不声称思考模式或参数语义完全等价。",
            "human_review_warning": "若出现 observed model failures，应结合各模型失败题数/比例与8192输出上限审阅；该状态不表示所有模型均能正常作答。" if observed_any else None,
            "qualification_rule": "150条均有非合成且完成的实际运行记录、身份/输入/预算完整，且无 API/transport/timeout/invalid_response/缺图/unrun 等程序阻断时可冻结。数学答错、拒答、解析失败、截断或空答作为观察到的模型行为单独报告，不自动阻止冻结。"}


def freeze_copy(report: dict, campaign: dict, stages: list[dict]) -> dict:
    configs = []
    for stage in stages:
        for model in stage["models"]:
            if model.get("declared_config"):
                configs.append({"stage": stage["spec"]["name"], "output_name": model["name"],
                                "source_config": str(model["config_path"].relative_to(ROOT)),
                                "source_config_file_sha256": sha_file(model["config_path"]),
                                "config_sha256": sha_json(normalize_project_config(model["declared_config"])),
                                "config": model["declared_config"]})
    return {
        "protocol_version": "development-protocol-v1", "status": report["state"],
        "campaign_manifest": str(output_path(DEFAULT_CAMPAIGN).relative_to(ROOT)),
        "campaign_manifest_sha256": sha_file(output_path(DEFAULT_CAMPAIGN)),
        "authorized_new_request_cap": 1000, "precheck_requests": report["precheck_requests"],
        "development_requests": report["development_requests"],
        "previous_72_requests_separate": 72, "formal_test_requests": report["formal_test_requests"],
        "system_prompt": report["system_prompt"], "prompt_version": report["prompt_version"],
        "datasets": report["datasets"], "configurations": configs,
        "source_versions": {"precheck": report.get("precheck_source_versions"),
                            "development": {m["output_name"]: m.get("source_versions") for m in report["development"]}},
        "backend_parameters": [{"stage": c["stage"], "output_name": c["output_name"], "backend": c["config"].get("backend")}
                               for c in configs],
        "parameter_modes_by_model": report["parameter_modes_by_model"],
        "mode_note": report["mode_note"],
        "human_review_warning": report["human_review_warning"],
        "qualification_rule": report["qualification_rule"],
        "metric_scope": report["accuracy_scope"],
        "observed_model_failures": {m["output_name"]: {"counts": m["observed_model_failures"], "failure_questions": m["observed_failure_count"], "failure_rate": m["observed_failure_rate"], "output_token_limit": m["config"].get("backend", {}).get("max_output_tokens")} for m in report["development"] if m.get("observed_failure_count")},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", default=DEFAULT_CAMPAIGN)
    args = parser.parse_args()
    campaign_path = output_path(args.campaign)
    campaign = read_json(campaign_path)
    if not campaign:
        print(f"Campaign manifest missing or unreadable: {campaign_path}")
        return 2
    stages = [load_stage(spec) for spec in campaign.get("stages", [])]
    # Avoid creating anything below a not-yet-created campaign root.
    if any(not s["batch"] for s in stages):
        print("Campaign batch logs are not all present yet; no report or freeze file was written.")
        return 2
    report = compare_and_audit(campaign, stages)
    report_dir = output_path("runs/campaign_1000/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    status = report["state"]
    report_path = report_dir / ("frozen_protocol.json" if status in {"frozen", "frozen_with_observed_model_failures"} else "candidate_with_issues.json")
    if status in {"frozen", "frozen_with_observed_model_failures"}:
        payload = freeze_copy(report, campaign, stages)
    else:
        payload = report
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dev_report = {k: report[k] for k in ("state", "development", "development_requests", "per_model_cap", "accuracy_scope", "qualification_rule")}
    dev_path = report_dir / "development_report.json"
    dev_path.write_text(json.dumps(dev_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"开发协议审计：{status}",
             f"新增请求：{report.get('new_campaign_requests') if report.get('new_campaign_requests') is not None else '未知'} / 1000；此前72次单独列示。",
             f"正式 test 请求：{report.get('formal_test_requests') if report.get('formal_test_requests') is not None else '无法确认'}。",
             report["accuracy_scope"]]
    if report.get("issues"):
        lines.append("待处理问题：")
        lines.extend("- " + x for x in report["issues"])
    for model in report.get("development", []):
        lines.append(f"{model.get('output_name')}: {'operationally_complete' if model.get('operationally_complete') else '有程序阻断'}; requests={model.get('requests')}; status={model.get('status_counts')}; correct/attempted={model.get('correct')}/{model.get('attempted')}; accuracy={model.get('accuracy_correct_over_attempted_dev_only')}; parsed_accuracy={model.get('accuracy_among_parsed_dev_only')}; coverage={model.get('answer_coverage_dev_only')}; observed={model.get('observed_model_failures')} ({model.get('observed_failure_rate')})")
        lines.extend("  - " + x for x in model.get("issues", []))
    txt_path = report_dir / "development_report.txt"
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {report_path}, {dev_path}, {txt_path}; state={status}")
    return 0 if status in {"frozen", "frozen_with_observed_model_failures"} else 1


if __name__ == "__main__":
    sys.exit(main())
