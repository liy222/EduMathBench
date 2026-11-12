#!/usr/bin/env python3
"""Summarize a local eval_batch run without making requests or exposing payloads."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = Path("runs/domestic_six_debug")
OUT_JSON = "runs/domestic_six_pilot_report.json"
OUT_CSV = "runs/domestic_six_pilot_report.csv"
OUT_TXT = "runs/domestic_six_pilot_report.txt"


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def read_jsonl(path: Path):
    rows = []
    try:
        with path.open(encoding="utf-8-sig") as stream:
            for line in stream:
                if line.strip():
                    value = json.loads(line)
                    if isinstance(value, dict):
                        rows.append(value)
    except (OSError, ValueError):
        return None
    return rows


def image_ids(metadata: dict) -> set[str] | None:
    dataset = metadata.get("dataset") or {}
    data_root = dataset.get("dataset_root")
    input_path = dataset.get("input_path")
    if not data_root or not input_path:
        return None
    rows = read_jsonl(Path(data_root) / input_path)
    if rows is None:
        return None
    return {r["id"] for r in rows if r.get("image_assets")}


def safe_error_code(attempt: dict) -> str | None:
    """Return only a bounded code or HTTP status; never serialize an error body."""
    body = attempt.get("raw_response")
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            if isinstance(code, (str, int)) and len(str(code)) <= 80:
                return str(code)
    status = attempt.get("http_status")
    return f"HTTP_{status}" if isinstance(status, int) else None


def local_error_evidence(attempt: dict) -> tuple[int | None, str, str]:
    """Extract transient evidence locally; callers must never serialize message."""
    status = attempt.get("http_status")
    body = attempt.get("raw_response")
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else ""
    message = error.get("message") if isinstance(error, dict) else ""
    return (status if isinstance(status, int) else None,
            str(code).lower() if isinstance(code, (str, int)) else "",
            str(message).lower() if isinstance(message, str) else "")


def error_categories(details_by_id: dict) -> list[str]:
    """Map current sanitized errors to a small fixed vocabulary; omit messages."""
    found = set()
    for detail in details_by_id.values():
        attempts = detail.get("attempts", []) if isinstance(detail, dict) else []
        for attempt in attempts:
            status, code, message = local_error_evidence(attempt)
            text = f"{code} {message}"
            if status == 402 and ("insufficient balance" in text or "balance" in text):
                found.add("余额不足")
            if status == 429:
                rpm = re.search(r"\b(\d{1,4})\s*(?:requests?\s*(?:/|per)\s*minute|rpm)\b", text)
                found.add(f"限流（{rpm.group(1)} RPM）" if rpm else "限流")
            if status == 400 and ("dimensions" in text or "width" in text or "height" in text or "shortest side" in text):
                found.add("图片尺寸限制")
    order = {"余额不足": 0, "限流": 1, "图片尺寸限制": 2}
    return sorted(found, key=lambda category: (0 if category.startswith("限流（") else order.get(category, 9), category))


def summarize_model(run_dir: Path, batch_row: dict, plan_row: dict | None) -> dict:
    name = batch_row.get("output_name") or (plan_row or {}).get("output_name") or run_dir.name
    metadata = read_json(run_dir / "run.json")
    preds = read_jsonl(run_dir / "predictions.jsonl")
    result = {
        "vendor": batch_row.get("vendor") or (plan_row or {}).get("vendor"),
        "output_name": name,
        "model": batch_row.get("model") or (plan_row or {}).get("model"),
        "state": batch_row.get("state"),
        "result_kind": batch_row.get("result_kind"),
        "parameter_mode": batch_row.get("parameter_mode"),
        "run_id": batch_row.get("run_id"),
        "metadata_available": isinstance(metadata, dict),
        "input_count": None,
        "remote_request_count": None,
        "request_reservations_complete": False,
        "known_usage_requests": None,
        "unknown_usage_requests": None,
        "observed_total_tokens": None,
        "attempted_questions": None,
        "unrun_questions": None,
        "response_count": 0,
        "parseable_answer_count": 0,
        "image_questions_attempted": 0,
        "image_questions_succeeded": 0,
        "text_questions_succeeded": 0,
        "finish_reason_length": 0,
        "final_content_empty": 0,
        "http_error_codes": {},
        "attempt_status_counts": {},
        "error_categories": [],
        "accuracy": None,
        "accuracy_scope": "debug小样本overall；非正式成绩",
        "config_sha256": None,
        "input_sha256": None,
        "manifest_sha256": None,
        "prompt_sha256": None,
        "prompt_version": None,
        "account_probe_status": "unknown",
    }
    if not isinstance(metadata, dict):
        return result

    dataset = metadata.get("dataset") or {}
    ident = metadata.get("identity") or {}
    reservations = metadata.get("remote_attempts")
    result.update({
        "input_count": dataset.get("input_count"),
        "config_sha256": ident.get("config_sha256"),
        "input_sha256": ident.get("input_sha256"),
        "manifest_sha256": ident.get("manifest_sha256"),
        "prompt_sha256": ident.get("prompt_sha256"),
        "prompt_version": metadata.get("prompt_version"),
        "run_id": metadata.get("run_id"),
    })
    if isinstance(reservations, list):
        known = [x.get("total_tokens") for x in reservations if isinstance(x, dict) and isinstance(x.get("total_tokens"), int)]
        result.update(remote_request_count=len(reservations), request_reservations_complete=True,
                      known_usage_requests=len(known), unknown_usage_requests=len(reservations)-len(known),
                      observed_total_tokens=sum(known))

    if preds is None:
        return result
    inputs = image_ids(metadata)
    statuses = {}
    details_dir = run_dir / "items"
    details_by_id = {}
    for row in preds:
        status = row.get("status")
        statuses[status] = statuses.get(status, 0) + 1
        if status == "ok":
            result["parseable_answer_count"] += 1
        if status == "unrun_budget_limit":
            result["unrun_questions"] = (result["unrun_questions"] or 0) + 1
        if row.get("attempted"):
            result["attempted_questions"] = (result["attempted_questions"] or 0) + 1
        path = details_dir / Path(row.get("detail_path", "")).name
        detail = read_json(path)
        if isinstance(detail, dict):
            details_by_id[row.get("id")] = detail
    result["attempted_questions"] = result["attempted_questions"] or 0
    result["unrun_questions"] = result["unrun_questions"] or 0
    result["status_counts"] = statuses
    for row in preds:
        detail = details_by_id.get(row.get("id"), {})
        attempts = detail.get("attempts") if isinstance(detail.get("attempts"), list) else []
        result["response_count"] += sum(1 for attempt in attempts if attempt.get("status") == "received")
        is_image = row.get("id") in inputs if inputs is not None else None
        if is_image and attempts:
            result["image_questions_attempted"] += 1
            if row.get("status") == "ok":
                result["image_questions_succeeded"] += 1
        if is_image is False and row.get("status") == "ok":
            result["text_questions_succeeded"] += 1
        for attempt in attempts:
            attempt_status = attempt.get("status", "unknown")
            result["attempt_status_counts"][attempt_status] = result["attempt_status_counts"].get(attempt_status, 0) + 1
            response = attempt.get("raw_response")
            if attempt.get("status") == "api_error":
                response_status = attempt.get("http_status")
                code = safe_error_code(attempt)
                label = f"HTTP_{response_status}|{code}" if isinstance(response_status, int) and code and not code.startswith("HTTP_") else (f"HTTP_{response_status}" if isinstance(response_status, int) else code)
                if label:
                    result["http_error_codes"][label] = result["http_error_codes"].get(label, 0) + 1
            if isinstance(response, dict):
                choices = response.get("choices")
                if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                    choice = choices[0]
                    if choice.get("finish_reason") == "length":
                        result["finish_reason_length"] += 1
                    msg = choice.get("message")
                    content = msg.get("content") if isinstance(msg, dict) else None
                    if content is None or (isinstance(content, str) and not content.strip()):
                        result["final_content_empty"] += 1
    overall = (batch_row or {}).get("overall")
    if isinstance(overall, dict):
        result["accuracy"] = overall.get("accuracy")
        result["accuracy_scope"] = "debug小样本；accuracy分母为attempted，unrun仅影响coverage；非正式成绩"
    result["error_categories"] = error_categories(details_by_id)
    if result["parseable_answer_count"] > 0:
        if result["text_questions_succeeded"] > 0 and result["image_questions_succeeded"] > 0:
            result["account_probe_status"] = "text_and_image_probe_passed"
        elif result["text_questions_succeeded"] > 0:
            result["account_probe_status"] = "text_probe_passed_image_unconfirmed"
        elif result["image_questions_succeeded"] > 0:
            result["account_probe_status"] = "image_probe_passed_text_unconfirmed"
    elif result["http_error_codes"]:
        result["account_probe_status"] = "request_errors_observed"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=str(DEFAULT_RUN), help="batch run directory (default: runs/domestic_six_debug)")
    parser.add_argument("--json", default=OUT_JSON, help="JSON output path")
    parser.add_argument("--csv", default=OUT_CSV, help="CSV output path")
    parser.add_argument("--txt", default=OUT_TXT, help="text output path")
    args = parser.parse_args()
    run = Path(args.run)
    if not run.is_absolute():
        run = ROOT / run
    run = run.resolve()
    batch = read_json(run / "batch.json") or {}
    summary = read_json(run / "batch_summary.json") or {}
    readiness = read_json(run / "readiness.json") or {}
    manifest_rows = (batch.get("identity") or {}).get("models", [])
    summary_rows = summary.get("models", [])
    by_output = {r.get("output_name"): r for r in summary_rows if isinstance(r, dict)}
    by_plan = {r.get("output_name"): r for r in manifest_rows if isinstance(r, dict)}
    names = list(dict.fromkeys([r.get("output_name") for r in manifest_rows if isinstance(r, dict)] +
                               [r.get("output_name") for r in summary_rows if isinstance(r, dict)]))
    models = [summarize_model(run / str(name), by_output.get(name, {}), by_plan.get(name)) for name in names]
    reservations_known = all(m["request_reservations_complete"] for m in models) and bool(models)
    requests = sum(m["remote_request_count"] for m in models if isinstance(m["remote_request_count"], int)) if reservations_known else None
    limit = readiness.get("max_requests_total")
    if limit is None:
        limit = batch.get("max_requests_total")
    live = batch.get("state") == "running" or summary.get("state") == "running"
    probes_passed = len(models) == 6 and all(m["account_probe_status"] == "text_and_image_probe_passed" for m in models)
    budget_ok = requests is not None and isinstance(limit, int) and requests <= limit
    normal_budget_stop = all(m.get("unrun_questions", 0) > 0 for m in models) and all(m.get("state") == "complete_with_issues" for m in models)
    api_errors_observed = any(any(key not in {"received", "unknown"} for key in m["attempt_status_counts"]) for m in models)
    report_state = "in_progress" if live else ("complete_with_issues" if probes_passed and budget_ok and normal_budget_stop else "issues_observed")
    pilot_outcome = "in_progress" if live else ("all_probes_passed_with_api_errors" if probes_passed and api_errors_observed else "all_probes_passed" if probes_passed else "api_or_probe_errors_observed")
    report = {
        "schema_version": 1,
        "run_directory": str(run),
        "generated_from_local_logs_only": True,
        "interim": bool(live),
        "state": report_state,
        "pilot_outcome": pilot_outcome,
        "batch_state": batch.get("state"),
        "summary_state": summary.get("state"),
        "models": models,
        "total_remote_requests_from_persisted_reservations": requests,
        "max_requests_total": limit,
        "request_cap_check": "within_cap" if budget_ok else ("exceeds_cap" if requests is not None and isinstance(limit, int) else "unknown_missing_metadata"),
        "request_accounting_complete": reservations_known,
        "all_six_text_and_image_probes_passed": probes_passed,
        "reporting_notes": [
            "Accuracy is a debug-only small-sample measure, not a formal score; API/interface success is reported separately.",
            "unrun_budget_limit questions are reported separately from failures.",
            "No question text, request payload, image bytes, credentials, or HTTP error bodies are included.",
            "Token usage is known only when persisted response usage was available; unknown is not treated as zero.",
        ],
    }
    for outpath, content in ((args.json, json.dumps(report, ensure_ascii=False, indent=2) + "\n"),):
        path = Path(outpath); path = path if path.is_absolute() else ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
    csv_path = Path(args.csv); csv_path = csv_path if csv_path.is_absolute() else ROOT / csv_path
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    flat_fields = ["vendor", "output_name", "model", "state", "remote_request_count", "known_usage_requests", "unknown_usage_requests", "observed_total_tokens", "attempted_questions", "unrun_questions", "response_count", "parseable_answer_count", "image_questions_attempted", "image_questions_succeeded", "text_questions_succeeded", "finish_reason_length", "final_content_empty", "http_error_codes", "account_probe_status", "accuracy", "accuracy_scope", "config_sha256", "input_sha256", "manifest_sha256", "prompt_sha256", "prompt_version"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=flat_fields, extrasaction="ignore")
        writer.writeheader()
        for model in models:
            row = dict(model); row["http_error_codes"] = json.dumps(model["http_error_codes"], ensure_ascii=False)
            writer.writerow(row)
    txt_path = Path(args.txt); txt_path = txt_path if txt_path.is_absolute() else ROOT / txt_path
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"API pilot report: {report_state}; outcome={pilot_outcome} (interim={str(bool(live)).lower()})",
             f"Persisted remote requests: {requests if requests is not None else 'unknown'} / {limit if limit is not None else 'unknown'}",
             "Accuracy values are debug-only and not formal scores."]
    for m in models:
        errors = ", ".join(f"{code}×{count}" for code, count in sorted(m["http_error_codes"].items())) or "none"
        vendor = m['vendor'] or m['output_name']
        failures = ", ".join(f"{code}×{count}" for code, count in sorted(m["attempt_status_counts"].items()) if code not in {"received", "unknown"}) or "无"
        categories = "；" + "、".join(m["error_categories"]) if m["error_categories"] else ""
        lines.append(f"{vendor}: {m['account_probe_status']}; requests={m['remote_request_count']}; attempted={m['attempted_questions']}; unrun={m['unrun_questions']}; responses={m['response_count']}; parsed={m['parseable_answer_count']}; image={m['image_questions_succeeded']}/{m['image_questions_attempted']}; errors={errors}{categories}; attempt failures={failures}")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.json}, {args.csv}, {args.txt}; state={report_state}; requests={requests}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
