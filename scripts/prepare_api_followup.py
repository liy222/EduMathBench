"""Prepare disabled follow-up configs from a completed pilot; never call APIs."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import eval_engine as engine


ROOT = Path(__file__).resolve().parents[1]


def prepare() -> dict:
    source = ROOT / "config/evaluation_domestic_six.json"
    original = engine.read_json(source)
    pilot = engine.read_json(ROOT / "runs/domestic_six_pilot_report.json")
    if pilot.get("interim") or pilot.get("total_remote_requests_from_persisted_reservations") != 60:
        raise engine.EvaluationError("Follow-up requires the completed 60-request pilot report")
    retest_path = ROOT / "runs/domestic_four_retest_report.json"
    retest = engine.read_json(retest_path) if retest_path.exists() else {}
    retested = {row["output_name"]: row for row in retest.get("models", [])} if not retest.get("interim", True) else {}
    target_dir = ROOT / "config/evaluation_after_pilot"
    target_dir.mkdir(exist_ok=True)
    entries = []
    for entry in original["models"]:
        old_path = engine.contained_path(ROOT, entry["config"])
        config = copy.deepcopy(engine.read_json(old_path))
        config["max_requests"] = 0
        config["description"] = "首轮60次预检之后的修订草稿；上限为0，未经新的预算授权不发送API请求。"
        config["preflight_status"] = "revised_offline_not_retested"
        config["backend"]["minimum_image_dimension"] = 32
        config["previous_pilot_config_sha256"] = engine.file_sha256(old_path)
        config["image_policy"] = "仅在原始必要单帧图片小于32像素时添加白边；不缩放、不改原文件。"
        result = retested.get(entry["output_name"], {})
        if entry["output_name"] == "qwen3.8-flash" and result.get("finish_reason_length", 0):
            config["backend"]["max_output_tokens"] = 8192
            config["output_limit_note"] = "12次复测中输出达到2048被截断；后续草稿提高至8192，尚未API验证，不保证每题均能完成。"
        if entry["output_name"] == "kimi-k3":
            config["backend"]["request_interval_seconds"] = 21
            config["backend"]["retry_backoff_seconds"] = 21
            config["rate_limit_note"] = "首轮实际账号返回组织上限3 RPM，后续至少间隔21秒；同组织其他调用仍可能触发限流。"
        if entry["output_name"] == "minimax-m3.1-flash":
            config["account_note"] = "第二轮单次文字账号探测通过，图片尚未测试。" if result.get("probe_passed") else "首轮HTTP402余额不足；用户处理余额后才能重新预检。"
        engine.normalize_config(config)
        target = target_dir / old_path.name
        engine.write_json(target, config)
        entries.append({**entry, "config": target.relative_to(ROOT).as_posix()})
    followup = copy.deepcopy(original)
    followup.update(
        version="domestic-six-after-pilot-v1",
        description="12次复测后的后续草稿：小图及限速已复测，千问8192输出上限尚未验证；全部调用禁用。" if retested else "首轮问题修订后的本地草稿：图片最短边补齐及Kimi限速；尚未API复测。",
        max_requests_total=0,
        budget_authorization="首轮60次及第二轮12次额度已用完；后续预算未授权，全部上限保持0。" if retested else "首轮60次额度已用完；后续预算未授权，全部上限保持0。",
        models=entries,
    )
    target = ROOT / "config/evaluation_domestic_six_followup.json"
    engine.write_json(target, followup)
    return {"followup_manifest": str(target), "max_requests_total": 0, "external_requests": 0, "models": len(entries)}


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(prepare(), ensure_ascii=False))
