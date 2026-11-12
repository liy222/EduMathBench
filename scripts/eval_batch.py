#!/usr/bin/env python3
"""Local readiness checks and bounded evaluation of provider batches.

``check`` never sends requests or reads answer tables. A ready report means
local prerequisites are present; it does not confirm model/account access.
"""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import sys

import eval_engine as engine


ROOT = Path(__file__).resolve().parents[1]
SPLITS = {"debug", "dev", "test", "all"}
STAGE_COUNTS = {"domestic_six_first": 6, "domestic_four_retest": 4, "domestic_two_precheck": 2, "domestic_six_development": 6}
STAGE_SPLITS = {"domestic_two_precheck": "debug", "domestic_six_development": "dev"}
ORDER_MATCH_STAGES = {"domestic_six_first", "domestic_six_development"}
OUTPUT_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,78}[A-Za-z0-9_-])?\Z")


def _positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _issue(code: str, detail: str, index: int | None = None) -> dict:
    row = {"code": code, "detail": detail}
    if index is not None:
        row["model_index"] = index
    return row


def _safe_read(path: Path):
    """Do not echo malformed input or accidentally inline secrets in errors."""
    try:
        return engine.read_json(path)
    except (OSError, ValueError, TypeError):
        raise engine.EvaluationError("JSON file is unreadable or invalid") from None


def _load_plan(manifest_path: Path, *, allow_test: bool, project_root: Path) -> tuple[dict, list[dict]]:
    root = project_root.resolve()
    manifest_path = manifest_path.resolve()
    report = {
        "schema_version": 1,
        "checked_at": engine.utc_now(),
        "manifest_path": str(manifest_path),
        "ready_for_api": False,
        "external_requests": 0,
        "account_probe_status": "not_run",
        "readiness_scope": "Local files, input integrity, configuration, credential presence and request limits only; API availability is untested.",
        "prompt_version": engine.PROMPT_VERSION,
        "prompt_sha256": engine.digest({"version": engine.PROMPT_VERSION, "system_prompt": engine.SYSTEM_PROMPT}),
        "models": [],
        "issues": [],
    }
    issues = report["issues"]
    try:
        manifest = _safe_read(manifest_path)
        report["batch_manifest_sha256"] = engine.file_sha256(manifest_path)
    except (OSError, engine.EvaluationError):
        issues.append(_issue("manifest_unreadable", "Cannot read the batch JSON manifest."))
        return report, []
    if not isinstance(manifest, dict):
        issues.append(_issue("manifest_schema", "Batch manifest must be an object."))
        return report, []
    if not isinstance(manifest.get("version"), str) or not manifest["version"].strip():
        issues.append(_issue("manifest_version", "Batch version must be a nonempty string."))
    stage = manifest.get("stage")
    report["stage"] = stage if isinstance(stage, str) else None
    expected_count = STAGE_COUNTS.get(stage) if isinstance(stage, str) else None
    report["expected_model_count"] = expected_count
    if expected_count is None:
        issues.append(_issue("manifest_stage", "Batch stage must be one of: " + ", ".join(STAGE_COUNTS) + "."))
        return report, []
    split = manifest.get("split", "debug")
    report["split"] = split if isinstance(split, str) else None
    if not isinstance(split, str) or split not in SPLITS:
        issues.append(_issue("invalid_split", "Batch split must be debug/dev/test/all."))
    if isinstance(split, str) and split in {"test", "all"} and not allow_test:
        issues.append(_issue("test_not_authorized", "Test/all requires explicit --allow-test."))
    if stage in STAGE_SPLITS and split != STAGE_SPLITS[stage]:
        issues.append(_issue("stage_split_mismatch", f"This stage requires the {STAGE_SPLITS[stage]} split; test/all execution is not part of this stage."))
    workers = manifest.get("parallel_workers", 1)
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 3:
        issues.append(_issue("invalid_parallel_workers", "parallel_workers must be an integer from 1 through 3."))
        report["parallel_workers"] = None
    else:
        report["parallel_workers"] = workers
    total_limit = manifest.get("max_requests_total")
    report["max_requests_total"] = total_limit if isinstance(total_limit, int) and not isinstance(total_limit, bool) else None
    if not _positive_int(total_limit):
        issues.append(_issue("batch_budget_required", "Set an explicit positive max_requests_total before running."))
    expected_manifest = manifest.get("expected_data_manifest_sha256")
    if stage in {"domestic_four_retest", "domestic_two_precheck", "domestic_six_development"} and expected_manifest is None:
        issues.append(_issue("dataset_hash_required", "This stage must pin expected_data_manifest_sha256."))
    if expected_manifest is not None and (not isinstance(expected_manifest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_manifest)):
        issues.append(_issue("invalid_expected_data_hash", "Expected dataset manifest hash must be SHA-256."))
        expected_manifest = None
    entries = manifest.get("models")
    if not isinstance(entries, list) or len(entries) != expected_count:
        code = {6: "six_models_required", 4: "four_models_required", 2: "two_models_required"}[expected_count]
        issues.append(_issue(code, f"The selected stage must contain exactly {expected_count} model entries."))
        return report, []
    seen = {"vendor": set(), "config": set(), "output_name": set(), "model": set()}
    plan = []
    dataset_cache = {}
    first_dataset = None
    first_input_order = None
    reserved = 0
    for number, entry in enumerate(entries, 1):
        row = {"model_index": number, "credential_configured": False, "api_probe_status": "not_run"}
        report["models"].append(row)
        if not isinstance(entry, dict):
            issues.append(_issue("model_schema", "Each model entry must be an object.", number))
            continue
        vendor = entry.get("vendor")
        output_name = entry.get("output_name")
        relative = entry.get("config")
        if not isinstance(vendor, str) or not vendor.strip():
            issues.append(_issue("invalid_vendor", "Each model needs a nonempty vendor.", number))
        else:
            row["vendor"] = vendor
            if vendor.strip().casefold() in seen["vendor"]:
                issues.append(_issue("duplicate_vendor", "Vendor entries must be distinct.", number))
            seen["vendor"].add(vendor.strip().casefold())
        if not isinstance(output_name, str) or not OUTPUT_NAME.fullmatch(output_name):
            issues.append(_issue("invalid_output_name", "Output name must be a 1-80 character filename starting with a letter/digit, using letters, digits, internal dots, underscores or hyphens, with no trailing dot or path separator.", number))
        else:
            row["output_name"] = output_name
            if output_name.casefold() in seen["output_name"]:
                issues.append(_issue("duplicate_output", "Model output folders must be distinct.", number))
            seen["output_name"].add(output_name.casefold())
        try:
            config_path = engine.contained_path(root, relative)
            if config_path.suffix.lower() != ".json":
                raise engine.EvaluationError("Config must be a JSON file")
        except (engine.EvaluationError, TypeError):
            issues.append(_issue("invalid_config_path", "Config must be a relative JSON path inside the project.", number))
            continue
        path_key = str(config_path).casefold()
        if path_key in seen["config"]:
            issues.append(_issue("duplicate_config", "Config paths must be distinct.", number))
        seen["config"].add(path_key)
        row["config_path"] = str(config_path)
        try:
            raw = _safe_read(config_path)
            if not isinstance(raw, dict):
                raise engine.EvaluationError("Config must be an object")
            raw = copy.deepcopy(raw)
            data_root = Path(raw.get("data_root", "data/benchmark_web_v0.3"))
            raw["data_root"] = str(data_root if data_root.is_absolute() else root / data_root)
            # Do not silently override a config split or allow different data.
            config = engine.normalize_config(raw)
        except (engine.EvaluationError, OSError, ValueError, TypeError, KeyError, AttributeError):
            issues.append(_issue("invalid_config", "Configuration is invalid; check schema, request fields and that credentials are provided only through an environment variable.", number))
            continue
        backend = config["backend"]
        model = backend["model"]
        row.update(model=model, parameter_mode=config.get("parameter_mode", "unspecified"), config_sha256=engine.digest(config), max_requests=config["max_requests"])
        if not isinstance(model, str) or not model.strip():
            issues.append(_issue("invalid_model", "Each config needs a model ID.", number))
        elif model.casefold() in seen["model"]:
            issues.append(_issue("duplicate_model", "Model IDs must be distinct.", number))
        else:
            seen["model"].add(model.casefold())
        if backend["type"] != "openai-compatible":
            issues.append(_issue("real_backend_required", "The domestic API batch must use real OpenAI-compatible backends; synthetic checks are separate.", number))
        env_name = backend["api_key_env"]
        if not isinstance(env_name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
            issues.append(_issue("invalid_key_env", "api_key_env must name an environment variable.", number))
            continue
        row["api_key_env"] = env_name
        row["credential_configured"] = bool(os.environ.get(env_name, "").strip())
        if not row["credential_configured"]:
            issues.append(_issue("credential_missing", "Required API-key environment variable is empty.", number))
        if not _positive_int(config["max_requests"]):
            issues.append(_issue("model_budget_required", "Set an explicit positive max_requests for this model.", number))
        else:
            reserved += config["max_requests"]
        if config["max_total_tokens"] == 0:
            issues.append(_issue("zero_token_limit", "A zero observed-token threshold would stop the run before its first request.", number))
        if config["split"] != split:
            issues.append(_issue("split_mismatch", "All configs must use the same split as the batch manifest.", number))
        dataset_key = (config["data_root"], config["split"])
        if first_dataset is None:
            first_dataset = dataset_key
        elif first_dataset != dataset_key:
            issues.append(_issue("dataset_mismatch", "All model configs must use the same data_root and split.", number))
        try:
            if dataset_key not in dataset_cache:
                dataset_cache[dataset_key] = engine.load_dataset(Path(config["data_root"]), config["split"])
            items, data_info = dataset_cache[dataset_key]
            row["dataset"] = data_info
            if expected_manifest and data_info["manifest_sha256"] != expected_manifest.lower():
                issues.append(_issue("dataset_manifest_mismatch", "Dataset manifest does not match the pinned SHA-256.", number))
            try:
                ordered_items = engine.prioritize_items(items, config)
                order_hash = engine.digest([item["id"] for item in ordered_items])
                row["input_order_sha256"] = order_hash
                if first_input_order is None:
                    first_input_order = order_hash
                elif stage in ORDER_MATCH_STAGES and first_input_order != order_hash:
                    issues.append(_issue("input_order_mismatch", "All six models must use the same complete input order, including priority IDs.", number))
                budget_count = min(config["max_requests"], len(ordered_items)) if _positive_int(config["max_requests"]) else 0
                row["first_budget_item_count"] = budget_count
                row["first_budget_image_count"] = sum(bool(item.get("image_assets")) for item in ordered_items[:budget_count])
            except engine.EvaluationError:
                issues.append(_issue("invalid_priority_ids", "Priority IDs must name existing input items; no model may run before every priority configuration validates.", number))
        except (engine.EvaluationError, OSError, ValueError, TypeError, KeyError):
            issues.append(_issue("invalid_inputs", "Input dataset or its declared SHA-256 failed validation.", number))
        plan.append({"entry": entry, "config": config, "report": row})
    report["allocated_request_limit"] = reserved
    if _positive_int(total_limit) and reserved > total_limit:
        issues.append(_issue("batch_budget_exceeded", "The sum of per-model request limits exceeds max_requests_total."))
    report["parameter_modes"] = {row.get("output_name", str(row["model_index"])): row.get("parameter_mode", "invalid_config") for row in report["models"]}
    report["ready_for_api"] = not issues
    report["budget_scope"] = "Request limits include retries and interrupted attempts across resume; observed token thresholds are not hard money caps."
    return report, plan


def check_batch(manifest_path: Path, output: Path, *, allow_test: bool = False, project_root: Path = ROOT) -> dict:
    """Write a zero-network prerequisite report; never read gold answers."""
    report, _ = _load_plan(Path(manifest_path), allow_test=allow_test, project_root=project_root)
    engine.write_json(Path(output) / "readiness.json", report)
    return report


# The unified project entry point uses this short name.
check = check_batch


def _batch_identity(readiness: dict) -> dict:
    return {
        "batch_manifest_sha256": readiness["batch_manifest_sha256"],
        "prompt_sha256": readiness["prompt_sha256"],
        "models": [{"config_sha256": row["config_sha256"], "dataset": row["dataset"], "input_order_sha256": row["input_order_sha256"], "output_name": row["output_name"]} for row in readiness["models"]],
    }


def _precheck_existing_runs(plan: list[dict], output: Path, *, resume: bool) -> None:
    """Reject a changed/foreign later model before sending an earlier call."""
    for selected in plan:
        row = selected["report"]
        folder = engine.contained_path(output, row["output_name"])
        run_path = folder / "run.json"
        if not run_path.exists():
            continue
        if not resume:
            raise engine.EvaluationError("An existing model run requires batch resume")
        stored = _safe_read(run_path)
        data = row["dataset"]
        expected = {
            "config_sha256": row["config_sha256"], "prompt_sha256": engine.digest({"version": engine.PROMPT_VERSION, "system_prompt": engine.SYSTEM_PROMPT}),
            "input_sha256": data["input_sha256"], "manifest_sha256": data["manifest_sha256"], "split": data["split"],
        }
        if not isinstance(stored, dict) or stored.get("identity") != expected:
            raise engine.EvaluationError("Existing model run identity does not match the selected batch")


def _model_summary(row: dict, state: str) -> dict:
    return {"vendor": row["vendor"], "model": row["model"], "output_name": row["output_name"], "parameter_mode": row["parameter_mode"], "state": state, "api_availability_confirmed": False}


def _evaluate_one(selected: dict, model_output: Path, *, resume: bool, allow_test: bool) -> dict:
    """Workers own one output folder and return data; they never write batches."""
    current = _model_summary(selected["report"], "running")
    current["started_at"] = engine.utc_now()
    try:
        # A provider adapter cannot mutate another model's frozen settings.
        config = copy.deepcopy(selected["config"])
        result = engine.execute_run(config, model_output, resume=resume and (model_output / "run.json").exists(), allow_test=allow_test)
        current.update(run_id=result["run_id"], synthetic=result["synthetic"], result_kind=result["result_kind"], status_counts=result["status_counts"], budget_usage=result["budget_usage"])
        score = engine.score_run(model_output)
        current["overall"] = score["overall"]
        current["state"] = "complete" if set(result["status_counts"]).issubset({"ok"}) else "complete_with_issues"
        current["api_availability_confirmed"] = result["status_counts"].get("ok", 0) > 0
    except Exception as exc:
        current.update(state="failed", error_type=type(exc).__name__, error_detail="Model execution or scoring failed. Inspect the model's existing run files; no exception payload is copied into this report.")
    current["finished_at"] = engine.utc_now()
    return current


def run_batch(manifest_path: Path, output: Path, *, resume: bool = False, allow_test: bool = False, project_root: Path = ROOT) -> dict:
    """Gate the whole batch before any model call; pin identities for resume."""
    output = Path(output).resolve()
    readiness, plan = _load_plan(Path(manifest_path), allow_test=allow_test, project_root=project_root)
    engine.write_json(output / "readiness.json", readiness)
    if not readiness["ready_for_api"]:
        summary = {"schema_version": 1, "stage": readiness.get("stage"), "expected_model_count": readiness.get("expected_model_count"), "state": "blocked_local_prerequisites", "external_requests": 0, "api_availability_confirmed": False, "issues": readiness["issues"], "readiness": str(output / "readiness.json")}
        # A rejected resume must not replace the existing batch's history.
        engine.write_json(output / "blocked_attempt.json", summary)
        return summary
    identity = _batch_identity(readiness)
    with engine.run_lock(output):
        batch_path = output / "batch.json"
        if batch_path.exists():
            previous = _safe_read(batch_path)
            if not resume:
                raise engine.EvaluationError("Batch exists; use --resume or a fresh output directory")
            if not isinstance(previous, dict) or previous.get("identity") != identity:
                raise engine.EvaluationError("Batch resume refused: manifest, configuration, prompt or input identity changed")
        else:
            if resume:
                raise engine.EvaluationError("Cannot resume a batch without batch.json")
            permitted = {".run.lock", "readiness.json", "blocked_attempt.json"}
            if any(path.name not in permitted for path in output.iterdir()):
                raise engine.EvaluationError("Batch output directory contains unrelated files")
            engine.write_json(batch_path, {"schema_version": 1, "created_at": engine.utc_now(), "identity": identity, "state": "running"})
        _precheck_existing_runs(plan, output, resume=resume)
        summary = {"schema_version": 1, "stage": readiness["stage"], "expected_model_count": readiness["expected_model_count"], "parallel_workers": readiness["parallel_workers"], "state": "running", "models": [_model_summary(selected["report"], "queued") for selected in plan], "identity": identity, "api_availability_confirmed": False, "api_availability_scope": "At least one successfully parsed answer per selected model; this does not confirm every text/image capability or mathematical correctness.", "started_at": engine.utc_now()}
        summary_path = output / "batch_summary.json"
        engine.write_json(summary_path, summary)
        if readiness["parallel_workers"] == 1:
            for index, selected in enumerate(plan):
                summary["models"][index]["state"] = "running"
                engine.write_json(summary_path, summary)
                model_output = engine.contained_path(output, selected["report"]["output_name"])
                summary["models"][index] = _evaluate_one(selected, model_output, resume=resume, allow_test=allow_test)
                engine.write_json(summary_path, summary)
        else:
            # Fixed per-model request allowances are validated before this
            # pool exists. Their sum never exceeds the batch allowance even
            # if every worker retries or resumes interrupted requests.
            with ThreadPoolExecutor(max_workers=readiness["parallel_workers"], thread_name_prefix="emb-model") as pool:
                futures = {}
                for index, selected in enumerate(plan):
                    model_output = engine.contained_path(output, selected["report"]["output_name"])
                    futures[pool.submit(_evaluate_one, selected, model_output, resume=resume, allow_test=allow_test)] = index
                    summary["models"][index]["state"] = "submitted"
                engine.write_json(summary_path, summary)
                # Only this controlling thread mutates/writes batch_summary.
                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        summary["models"][index] = future.result()
                    except Exception as exc:
                        failed = _model_summary(plan[index]["report"], "failed")
                        failed.update(error_type=type(exc).__name__, error_detail="Worker failed; exception payload omitted.")
                        summary["models"][index] = failed
                    engine.write_json(summary_path, summary)
        if any(row["state"] == "failed" for row in summary["models"]):
            summary["state"] = "failed"
        else:
            summary["state"] = "complete" if all(row["state"] == "complete" for row in summary["models"]) else "complete_with_issues"
        summary["finished_at"] = engine.utc_now()
        # Read committed reservations even when execute_run raised after sending.
        # A failed run must never be reported as zero-cost merely because its
        # normal return value was unavailable.
        request_count = 0
        accounting_complete = True
        for selected in plan:
            run_path = output / selected["report"]["output_name"] / "run.json"
            if run_path.exists():
                try:
                    stored = _safe_read(run_path)
                    if "remote_attempts" in stored:
                        request_count += engine.budget_usage(stored)["remote_request_count"]
                    else:
                        # Used by callers/tests that replace the run engine.
                        found = next((row for row in summary["models"] if row["output_name"] == selected["report"]["output_name"]), {})
                        request_count += found.get("budget_usage", {}).get("remote_request_count", 0)
                except (engine.EvaluationError, TypeError, KeyError, AttributeError):
                    accounting_complete = False
        summary["external_requests"] = request_count if accounting_complete else None
        summary["request_accounting_complete"] = accounting_complete
        summary["api_availability_confirmed"] = len(summary["models"]) == len(plan) and all(row.get("status_counts", {}).get("ok", 0) > 0 for row in summary["models"])
        engine.write_json(summary_path, summary)
        metadata = _safe_read(batch_path)
        metadata.update(state=summary["state"], finished_at=summary["finished_at"])
        engine.write_json(batch_path, metadata)
        return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "run"])
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/evaluation_domestic_six.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-test", action="store_true")
    args = parser.parse_args(argv)
    try:
        # The direct CLI has the same credential-file behavior as the project
        # entry point. Library checks deliberately leave process env untouched.
        from eval_credentials import load_project_env
        load_project_env()
        if args.command == "check":
            result = check_batch(args.manifest, args.output, allow_test=args.allow_test)
            successful = result["ready_for_api"]
        else:
            result = run_batch(args.manifest, args.output, resume=args.resume, allow_test=args.allow_test)
            successful = result["state"] in {"complete", "complete_with_issues"}
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if successful else 2
    except (engine.EvaluationError, OSError, ValueError, KeyError, TypeError) as exc:
        # In particular, never echo an unexpected HTTP/provider exception body.
        print(f"Batch error ({type(exc).__name__}); see local reports and run files. Exception payload omitted.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
