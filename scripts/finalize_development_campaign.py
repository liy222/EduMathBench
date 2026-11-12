"""Publish a checked development-campaign summary; this never invokes a model."""
from __future__ import annotations

import json
from pathlib import Path

import eval_engine as engine
import run_development_campaign as campaign


def finalize() -> dict:
    definition = engine.read_json(campaign.CAMPAIGN)
    directory = campaign.OUT / "reports"
    protocol_path = directory / "frozen_protocol.json"
    protocol = engine.read_json(protocol_path)
    report = engine.read_json(directory / "development_report.json")
    if protocol.get("status") not in {"frozen", "frozen_with_observed_model_failures"}:
        raise engine.EvaluationError("Protocol audit has not qualified this campaign for publication")
    if protocol.get("campaign_manifest_sha256") != engine.file_sha256(campaign.CAMPAIGN):
        raise engine.EvaluationError("Campaign manifest changed after the protocol audit")
    accounting = campaign.request_accounting(definition)
    if accounting["inflight"] or accounting["new_requests"] > 1000:
        raise engine.EvaluationError("Active requests or invalid campaign request accounting")
    if protocol["precheck_requests"] + protocol["development_requests"] != accounting["new_requests"]:
        raise engine.EvaluationError("Independent audit and persisted request counts disagree")
    if protocol.get("formal_test_requests") != 0:
        raise engine.EvaluationError("This task did not authorize formal test evaluation")
    models = report["development"]
    if len(models) != 6 or any(m.get("attempted") != 150 or not m.get("operationally_complete") for m in models):
        raise engine.EvaluationError("All six models must have 150 complete operationally valid attempts")
    software = engine.read_json(campaign.OUT / "software_validation.json")
    io = engine.read_json(campaign.OUT / "io_resume_verification.json")
    if not software.get("passed") or not io.get("passed") or io.get("requests_compared") != 900:
        raise engine.EvaluationError("Software validation or IO-equivalence evidence is missing")
    table = []
    for model in models:
        row = {
            "model": model["model"], "attempted": model["attempted"],
            "correct": model["correct"],
            "accuracy": model["accuracy_correct_over_attempted_dev_only"],
            "status_counts": model["status_counts"], "requests": model["requests"],
            "observed_failure_questions": model.get("observed_failure_count", 0),
            "tokens": model.get("tokens"),
        }
        table.append(row)
    result = {
        "status": protocol["status"], "completed_at": engine.utc_now(),
        "step1_precheck": "passed", "step2_dev150_and_protocol": "complete",
        "unique_development_questions": 150, "development_answer_records": 900,
        "models": table, "accounting": accounting, "formal_test_requests": 0,
        "protocol": str(protocol_path), "protocol_sha256": engine.file_sha256(protocol_path),
        "software_tests_passed": software["tests"], "request_body_comparison_count": 900,
        "scope": "Development set only. Correct/attempted is primary; model output failures are retained. No formal test ranking.",
    }
    engine.write_json(campaign.OUT / "completion.json", result)
    lines = [
        "EduMathBench：步骤1、2完成说明",
        "步骤1：千问8192输出与MiniMax图像输入补验通过。",
        "步骤2：六家均完成同一150题开发集，共900份答题记录，参数与评分规则已冻结。",
        f"协议状态：{protocol['status']}；模型未返回有效最终答案的记录仍保留并计入主准确率。",
        f"本轮记账请求：{accounting['new_requests']}/1000（补验{protocol['precheck_requests']}、开发阶段{protocol['development_requests']}，包含重试及中断预留）；此前72次单独列示。",
        "模型\t正确/已尝试\t主准确率\t输出异常题数（含截断）",
    ]
    for row in table:
        lines.append(f"{row['model']}\t{row['correct']}/{row['attempted']}\t{row['accuracy']:.2%}\t{row['observed_failure_questions']}")
    lines += [
        "以上为开发集结果，正式测试集未运行。各厂商思考模式与温度差异在冻结协议中如实保存。",
        f"软件测试：{software['tests']}项通过；IO修订前后900个请求内容逐字节一致，原题库与图片未改变。",
        "原始请求、响应、重试、中断及用量未知项分别留痕；协议与详细开发报告见reports/。",
    ]
    (campaign.OUT / "完成说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    for filename in ("campaign.json", "campaign_summary.json"):
        path = campaign.OUT / filename
        meta = engine.read_json(path)
        meta.setdefault("execution_completion_state", meta.get("state"))
        meta.update(state=protocol["status"], protocol=str(protocol_path), protocol_sha256=result["protocol_sha256"], completed_at=result["completed_at"])
        engine.write_json(path, meta)
    return result


if __name__ == "__main__":
    value = finalize()
    print(json.dumps({key: value[key] for key in ("status", "development_answer_records", "accounting", "formal_test_requests")}, ensure_ascii=False))
