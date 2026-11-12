#!/usr/bin/env python3
"""Summarize the targeted four-provider retest from local logs only."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys

import summarize_api_pilot as pilot

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = Path("runs/domestic_four_retest_12")
OUT_JSON = "runs/domestic_four_retest_report.json"
OUT_TXT = "runs/domestic_four_retest_report.txt"
PROBLEM_ID = "EMB-P-WEB2-TIKU-1754090"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PARSE_FAILURE_REASONS = {
    "standalone_answer": "无法提取唯一选项",
    "explicit_final_answer": "无法提取唯一选项",
    "no_answer": "未提取到选项答案",
    "ambiguous_answer": "答案格式含糊",
    "invalid_answer": "答案不在选项范围内",
    "empty_response": "模型回复为空",
    "finish_reason_length": "回复达到长度上限",
    "missing_unique_final_answer": "未输出唯一最终答案",
}


def read_json(path: Path):
    return pilot.read_json(path)


def detail_for(run_dir: Path, prediction: dict) -> dict:
    path = run_dir / "items" / Path(prediction.get("detail_path", "")).name
    value = read_json(path)
    return value if isinstance(value, dict) else {}


def short_errors(details: dict[str, dict]) -> list[dict]:
    errors = []
    for item_id, detail in details.items():
        for attempt in detail.get("attempts", []):
            if attempt.get("status") != "api_error":
                continue
            code = pilot.safe_error_code(attempt) or "unknown"
            categories = pilot.error_categories({item_id: {"attempts": [attempt]}})
            errors.append({"code": code, "reason": categories[0] if categories else "未分类接口错误"})
    return errors


def image_evidence(detail: dict) -> list[dict]:
    result = []
    for item in detail.get("image_processing", []) if isinstance(detail.get("image_processing"), list) else []:
        if not isinstance(item, dict):
            continue
        result.append({k: item.get(k) for k in ("source_dimensions", "derived_dimensions", "source_sha256", "derived_sha256")})
    return result


def image_dimensions_passed(prediction: dict, detail: dict) -> tuple[bool, list[dict]]:
    ev = image_evidence(detail)
    attempts = detail.get("attempts", [])
    accepted = any(a.get("status") == "received" for a in attempts if isinstance(a, dict))
    no_bad_request = not any(a.get("http_status") == 400 for a in attempts if isinstance(a, dict))
    small_ev = [x for x in ev if x.get("source_dimensions") == [8, 35]]
    full_evidence = len(small_ev) == 4 and len({x.get("source_sha256") for x in small_ev}) == 4 and all(
        x.get("source_dimensions") == [8, 35]
        and x.get("derived_dimensions") == [32, 35]
        and isinstance(x.get("source_sha256"), str) and SHA256_RE.fullmatch(x["source_sha256"])
        and isinstance(x.get("derived_sha256"), str) and SHA256_RE.fullmatch(x["derived_sha256"])
        and x["source_sha256"] != x["derived_sha256"]
        for x in small_ev
    )
    return accepted and no_bad_request and full_evidence, ev


def parse_failure_reason(prediction: dict, detail: dict) -> str | None:
    if prediction.get("status") == "ok":
        return None
    reason = detail.get("parse_reason") or prediction.get("parse_reason")
    if reason in PARSE_FAILURE_REASONS:
        return PARSE_FAILURE_REASONS[reason]
    if prediction.get("status") == "parse_failure":
        return "无法解析选项答案"
    return None


def attempt_finish_reasons(detail: dict) -> list[str]:
    found = []
    for attempt in detail.get("attempts", []):
        response = attempt.get("raw_response") if isinstance(attempt, dict) else None
        choices = response.get("choices", []) if isinstance(response, dict) else []
        if choices and isinstance(choices[0], dict) and choices[0].get("finish_reason") == "length":
            found.append("length")
    return found


def minimum_interval(metadata: dict) -> tuple[float | None, int]:
    stamps = []
    reservations = metadata.get("remote_attempts")
    for reservation in reservations if isinstance(reservations, list) else []:
        try:
            stamps.append(datetime.fromisoformat(reservation["started_at"].replace("Z", "+00:00")).timestamp())
        except (KeyError, TypeError, ValueError):
            continue
    gaps = [b-a for a, b in zip(sorted(stamps), sorted(stamps)[1:])]
    return (min(gaps) if gaps else None, len(stamps))


def http_429_count(details: dict[str, dict]) -> int:
    return sum(
        1 for detail in details.values()
        for attempt in detail.get("attempts", [])
        if isinstance(attempt, dict) and attempt.get("http_status") == 429
    )


def persisted_request_total(models: list[dict]) -> int | None:
    values = [m.get("requests") for m in models]
    return sum(values) if values and all(isinstance(n, int) for n in values) else None


def self_check() -> None:
    sha_a, sha_b = "a" * 64, "b" * 64
    attempt = {"status": "received", "http_status": 200, "raw_response": {"choices": [{"finish_reason": "stop"}]}}
    evidence = [{"source_dimensions": [8, 35], "derived_dimensions": [32, 35], "source_sha256": str(n) * 64, "derived_sha256": sha_b} for n in range(4)]
    ok, _ = image_dimensions_passed({"status": "parse_failure"}, {"attempts": [attempt], "image_processing": evidence})
    assert ok, "all four verified image derivations should pass independently of answer parsing"
    main_image = {"source_dimensions": [157, 139], "derived_dimensions": [157, 139], "source_sha256": sha_a, "derived_sha256": sha_a}
    assert image_dimensions_passed({"status": "ok"}, {"attempts": [attempt], "image_processing": [main_image, *evidence]})[0], "unchanged geometry image must not count as a fifth small image"
    assert not image_dimensions_passed({"status": "ok"}, {"attempts": [attempt], "image_processing": evidence[:1]})[0]
    assert parse_failure_reason({"status": "parse_failure"}, {"parse_reason": "finish_reason_length"}) == "回复达到长度上限"
    assert http_429_count({"x": {"attempts": [{"http_status": 429, "raw_response": {"error": {"code": "CUSTOM_THROTTLE"}}}]}}) == 1
    assert persisted_request_total([{"requests": 3}, {"requests": None}]) is None
    print("synthetic checks passed")


def summarize(run: Path, manifest: dict) -> dict:
    entries = manifest.get("models", [])
    summary = read_json(run / "batch_summary.json") or {}
    batch = read_json(run / "batch.json") or {}
    by_output = {r.get("output_name"): r for r in summary.get("models", []) if isinstance(r, dict)}
    by_plan = {r.get("output_name"): r for r in (batch.get("identity") or {}).get("models", []) if isinstance(r, dict)}
    all_models = []
    for entry in entries:
        name = entry.get("output_name")
        run_dir = run / str(name)
        basic = pilot.summarize_model(run_dir, by_output.get(name, {}), by_plan.get(name))
        metadata = read_json(run_dir / "run.json") or {}
        preds = pilot.read_jsonl(run_dir / "predictions.jsonl")
        preds_available = preds is not None
        preds = preds or []
        details = {p.get("id"): detail_for(run_dir, p) for p in preds if p.get("id")}
        by_id = {p.get("id"): p for p in preds}
        attempted = sum(bool(p.get("attempted")) for p in preds)
        parsed = sum(p.get("status") == "ok" for p in preds)
        requests = metadata.get("remote_attempts")
        requests = len(requests) if isinstance(requests, list) else None
        item = {
            "output_name": name, "model": basic.get("model") or entry.get("model") or (metadata.get("config") or {}).get("backend", {}).get("model"),
            "probe_goal": entry.get("probe_goal") or (metadata.get("config") or {}).get("probe_goal"), "requests": requests,
            "attempted": attempted if preds_available else None, "parsed": parsed if preds_available else None,
            "prediction_log_available": preds_available,
            "finish_reason_length": sum(len(attempt_finish_reasons(d)) for d in details.values()),
            "parse_failure_reasons": [reason for i, p in by_id.items() if (reason := parse_failure_reason(p, details.get(i, {})))],
            "errors": short_errors(details), "predictions": by_id,
            "details": details, "metadata": metadata,
        }
        all_models.append(item)

    # Probe checks are specific to the authorized retest goals.
    qd_pass = True
    for name in ("qwen3.8-flash", "doubao-seed-2.1-lite"):
        model = next((m for m in all_models if m["output_name"] == name), {})
        pred = model.get("predictions", {}).get(PROBLEM_ID, {})
        detail = model.get("details", {}).get(PROBLEM_ID, {})
        dim_pass, ev = image_dimensions_passed(pred, detail)
        answer_pass = pred.get("status") == "ok"
        model["problem_item"] = {
            "status": pred.get("status", "missing"),
            "image_dimensions_retest_passed": dim_pass,
            "problem_answer_parse_passed": answer_pass,
            "parse_failure_reason": parse_failure_reason(pred, detail),
            "finish_reason_length": bool(attempt_finish_reasons(detail)),
            "http_400_count": sum(a.get("http_status") == 400 for a in detail.get("attempts", []) if isinstance(a, dict)),
            "image_processing": ev,
        }
        qd_pass = qd_pass and dim_pass and answer_pass

    kimi = next((m for m in all_models if m["output_name"] == "kimi-k3"), {})
    min_gap, stamp_count = minimum_interval(kimi.get("metadata", {}))
    kimi429 = http_429_count(kimi.get("details", {}))
    kimi["minimum_request_interval_seconds"] = min_gap
    kimi["http_429_count"] = kimi429
    kimi["rate_limit_retest_passed"] = (stamp_count >= 4 and (kimi.get("parsed") or 0) >= 4 and kimi429 == 0
                                         and (min_gap or 0) >= 20.9)

    mini = next((m for m in all_models if m["output_name"] == "minimax-m3.1-flash"), {})
    mini["probe_passed"] = (mini.get("parsed") or 0) >= 1
    mini["image_test"] = "未测试（本轮仅文字账号探测）"

    total = persisted_request_total(all_models)
    cap_ok = total is not None and total <= 12
    batch_state = batch.get("state")
    live = batch_state == "running"
    all_goals = qd_pass and kimi.get("rate_limit_retest_passed", False) and mini.get("probe_passed", False)
    return {
        "stage": manifest.get("stage"), "batch_state": batch_state, "interim": bool(live),
        "state": "interim" if live else ("missing_run_status" if batch_state is None else ("complete" if all_goals and cap_ok else "issues_observed")),
        "models": all_models, "total_requests": total, "request_cap": 12,
        "within_cap": cap_ok, "four_goals_satisfied": bool(all_goals and cap_ok),
        "previous_run_requests": 60, "combined_max_requests": 72,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=str(DEFAULT_RUN))
    parser.add_argument("--manifest", default="config/evaluation_retest_12.json")
    parser.add_argument("--json", default=OUT_JSON)
    parser.add_argument("--txt", default=OUT_TXT)
    parser.add_argument("--self-check", action="store_true", help="run local synthetic assertions only")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return 0
    run = Path(args.run); run = (run if run.is_absolute() else ROOT / run).resolve()
    manifest_path = Path(args.manifest); manifest_path = manifest_path if manifest_path.is_absolute() else ROOT / manifest_path
    manifest = read_json(manifest_path) or {}
    report = summarize(run, manifest)
    safe = {k: v for k, v in report.items() if k != "models"}
    safe["models"] = [{k: v for k, v in model.items() if k not in {"predictions", "details", "metadata"}} for model in report["models"]]
    for out in (args.json,):
        path = Path(out); path = path if path.is_absolute() else ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(safe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"问题项复测：{report['state']}（interim={str(report['interim']).lower()}）",
             f"本次持久化请求 {report['total_requests'] if report['total_requests'] is not None else '未知'}/12；上次60次，本次最多12次，合计最多72次。",
             f"四项目标：{'满足' if report['four_goals_satisfied'] else '未全部满足或仍待完成'}；回答解析不代表正式数学成绩。"]
    for m in report["models"]:
        err = "、".join(f"{e['code']}（{e['reason']}）" for e in m["errors"]) or "无"
        lines.append(f"{m['model']}: goal={m['probe_goal']}; requests={m['requests']}; attempted={m['attempted']}; parsed={m['parsed']}; errors={err}")
        if "problem_item" in m:
            p = m["problem_item"]
            lines.append(f"  问题题 {PROBLEM_ID}: status={p['status']}; 图片尺寸复测={'通过' if p['image_dimensions_retest_passed'] else '未通过'}（4张8x35→32x35）；答案解析={'通过' if p['problem_answer_parse_passed'] else '未通过'}；截断={'是' if p['finish_reason_length'] else '否'}；解析原因={p['parse_failure_reason'] or '无'}")
        if m["output_name"] == "kimi-k3":
            gap = m["minimum_request_interval_seconds"]
            lines.append(f"  Kimi: 最小间隔={gap if gap is not None else '未知'}秒；HTTP429={m['http_429_count']}；目标={'满足' if m['rate_limit_retest_passed'] else '未满足'}")
        if m["output_name"] == "minimax-m3.1-flash":
            lines.append(f"  MiniMax: 账号文字探测={'通过' if m['probe_passed'] else '未通过'}；图片={m['image_test']}")
    txt = Path(args.txt); txt = txt if txt.is_absolute() else ROOT / txt
    txt.parent.mkdir(parents=True, exist_ok=True)
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.json}, {args.txt}; state={report['state']}; requests={report['total_requests']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
