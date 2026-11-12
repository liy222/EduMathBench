"""Create an isolated public copy; never alter the local frozen benchmark."""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil

from eval_credentials import KEY_NAMES, load_project_env


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "deliverables/github_public_repo"
TEXT = {".py", ".md", ".txt", ".json", ".jsonl", ".csv", ".html", ".js", ".mjs", ".cjs", ".ps1", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".xml", ".sql", ".sh"}
SKIP = {"node_modules", "__pycache__", ".git", ".local_browser_profile", ".profiles", ".runtime_deps"}
MODEL_LABEL = re.compile(r"Codex|DeepSeek|Doubao|ChatGPT|GPT|Qwen|GLM|Gemini|Claude|MiniMax|^reviewer_\d+$", re.I)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export() -> dict:
    if DEST.exists() and any(DEST.iterdir()):
        raise RuntimeError("Public destination is nonempty; refusing to overwrite it")
    DEST.mkdir(parents=True, exist_ok=True)
    data_rel = Path("data/benchmark_web_v0.3")
    data = ROOT / data_rel
    original = [json.loads(s) for s in (data / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines() if s.strip()]
    labels = sorted({str(q.get("release_review", {}).get("reviewer_as_submitted")) for q in original}
                    - {"", "None"})
    private_labels = [s for s in labels if not MODEL_LABEL.search(s)]
    replacements = {s: f"reviewer_{number:02d}" for number, s in enumerate(private_labels, 1)}
    load_project_env()
    actual_keys = [os.environ.get(name, "") for name in KEY_NAMES if len(os.environ.get(name, "")) >= 8]

    def redact(text: str, paths: bool = True) -> str:
        for name, alias in replacements.items():
            text = text.replace(name, alias)
            escaped = json.dumps(name, ensure_ascii=True)[1:-1]
            text = text.replace(escaped, alias).replace(escaped.upper(), alias)
        if paths:
            for prefix in ("D:/EduMathBench/", "D:\\EduMathBench\\", "D:\\\\EduMathBench\\\\"):
                text = text.replace(prefix, "")
            text = re.sub(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"'<>]+[\\/]+", "[local-user]/", text)
        return text

    def copy_file(source: Path, relative: Path, *, preserve: bool = False) -> None:
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in TEXT and not preserve:
            text = source.read_text(encoding="utf-8-sig")
            target.write_text(redact(text, paths=relative.parts[0] not in {"scripts", "tests"}), encoding="utf-8")
        else:
            shutil.copyfile(source, target)

    for folder in ("scripts", "tests", "config", "docs", "templates"):
        for source in (ROOT / folder).rglob("*"):
            if source.is_file() and not SKIP.intersection(source.relative_to(ROOT).parts):
                copy_file(source, source.relative_to(ROOT))
    for name in ("运行评测流程.ps1", "运行网页题库流程.ps1", "程序使用清单.md", "国产六模型运行说明.txt", "COLLECTION_SPEC.md"):
        copy_file(ROOT / name, Path(name))
    copy_file(ROOT / "README.md", Path("docs/local_progress_history.md"))
    for source in data.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(ROOT)
        sub = source.relative_to(data)
        if sub.as_posix() in {"questions.jsonl", "questions.csv", "manifest.json"}:
            continue
        if sub.parts[0] == "reports" and source.suffix.lower() in {".png", ".jpg"}:
            continue
        preserve = sub.parts[0] in {"inputs", "answers", "assets", "splits"}
        copy_file(source, relative, preserve=preserve)
    public_questions = [json.loads(redact(json.dumps(q, ensure_ascii=False))) for q in original]
    core = ("id", "question", "options", "answer", "grade", "module", "difficulty", "parent_id", "family_id")
    assert all(all(a.get(k) == b.get(k) for k in core) for a, b in zip(original, public_questions))
    qpath = DEST / data_rel / "questions.jsonl"
    qpath.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in public_questions), encoding="utf-8")
    by_id = {q["id"]: q for q in public_questions}
    with (data / "questions.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        old_csv = list(reader)
    csv_path = DEST / data_rel / "questions.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in old_csv:
            record = json.loads(row["record_json"])
            row = {key: redact(value) for key, value in row.items()}
            row["record_json"] = json.dumps(by_id[record["id"]], ensure_ascii=False)
            writer.writerow(row)
    original_manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    manifest = json.loads(json.dumps(original_manifest))
    manifest["version"] += "-public1"
    manifest["questions_sha256"], manifest["csv_sha256"] = sha(qpath), sha(csv_path)
    manifest["public_export"] = {
        "questions": {"path": "questions.jsonl", "sha256": sha(qpath)},
        "csv": {"path": "questions.csv", "sha256": sha(csv_path)},
        "source_manifest_sha256": sha(data / "manifest.json"),
        "source_questions_sha256": sha(data / "questions.jsonl"),
        "metadata_anonymized": True, "model_inputs_and_answers_unchanged": True,
    }
    dump(DEST / data_rel / "manifest.json", manifest)
    public_manifest_hash = sha(DEST / data_rel / "manifest.json")
    for path in (DEST / "config").rglob("*.json"):
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(obj, dict):
            continue
        if "max_requests" in obj: obj["max_requests"] = 0
        if "max_requests_total" in obj: obj["max_requests_total"] = 0
        if "expected_data_manifest_sha256" in obj: obj["expected_data_manifest_sha256"] = public_manifest_hash
        dump(path, obj)
    selected = [
        "runs/domestic_six_pilot_report.json", "runs/domestic_six_pilot_report.csv", "runs/domestic_six_pilot_report.txt",
        "runs/domestic_four_retest_report.json", "runs/domestic_four_retest_report.txt",
        "runs/campaign_1000/completion.json", "runs/campaign_1000/完成说明.txt",
        "runs/campaign_1000/software_validation.json", "runs/campaign_1000/io_resume_verification.json",
        "runs/campaign_1000/reports/development_report.json", "runs/campaign_1000/reports/development_report.txt",
        "runs/campaign_1000/reports/frozen_protocol.json",
    ]
    for relative in selected:
        copy_file(ROOT / relative, Path(relative))
    for source in (ROOT / "runs/campaign_1000/development").glob("*/predictions.jsonl"):
        copy_file(source, source.relative_to(ROOT))
    for source in (ROOT / "runs/campaign_1000/reports/rechecked_scores").glob("*.json"):
        copy_file(source, source.relative_to(ROOT))
    (DEST / ".gitignore").write_text(".env*\n!.env.example\n**/__pycache__/\n**/node_modules/\n.runtime_deps/\n**/.profiles/\n**/.local_browser_profile/\n**/*browser_profile*/\n*.zip\n*.rar\n*.log\n/tmp/\n/deliverables/\n/runs/**/items/\n/runs/**/run.json\n/runs/**/requests/\n/runs/**/responses/\n/runs/**/.run.lock\n/runs/**/implementation/\n", encoding="utf-8")
    (DEST / ".gitattributes").write_text("# Preserve the exact bytes used by dataset SHA-256 manifests.\n* -text\n", encoding="utf-8")
    requirement_lines = []
    for package in ("Pillow", "sympy", "lxml"):
        try: requirement_lines.append(package + "==" + importlib.metadata.version(package))
        except importlib.metadata.PackageNotFoundError: pass
    (DEST / "requirements.txt").write_text("\n".join(requirement_lines) + "\n", encoding="utf-8")
    (DEST / "README.md").write_text('''# EduMathBench

中文初中数学选择题基准的采集、处理与评测程序。当前题库包含1500道原题与300道助手生成的变式，保留来源及生成/复核记录。

## 当前状态

- 原题：363道历史沿用题、1137道网页采集题；不把历史沿用部分包装为本次爬虫成果。
- 开发集：150道原题，每年级50道，无变式；测试集：1350道原题和300道变式。
- 六家各完成150题开发实验，共900份答题记录；本轮记账922/1000次，正式测试集未运行。
- 提示词`emb-choice-v1`，输出上限8192；保留各厂商思考/温度差异，结果仅为开发集表现。

## 文件

- `scripts/`、`tests/`：爬虫、清洗、结构/数学辅助检查、评测、限次续跑及协议审计程序。
- `data/benchmark_web_v0.3/`：1800题JSONL/CSV、无答案输入、独立答案表、必要原图、分集和离线浏览页。
- `runs/campaign_1000/完成说明.txt`：开发集结果；`reports/frozen_protocol.json`保存原本地实验协议。
- `runs/campaign_1000/development/*/predictions.jsonl`：逐题最终选项及状态，未发布含账户信息的原始HTTP日志。
- `config/api_keys.env.example`：空密钥模板。公开副本中的已有配置调用上限均设为0，避免误调用。

## 本地运行

建议使用本项目实际验证过的Python 3.12环境。

```powershell
python -m pip install -r requirements.txt
python scripts/edumath_web.py eval-self-test
python -m unittest discover -s tests -p test_eval_engine.py
```

双击`data/benchmark_web_v0.3/完整题库浏览.html`可离线浏览。实际API评测需在本机配置密钥、明确预算并主动启用；请勿将`.env.local`提交或发送给他人。爬虫浏览器依赖见`scripts/site_crawler/package.json`，需正常登录并遵循站点访问限制。

## 公开副本与复现边界

本副本对非模型复核者标签匿名化，并整理文档/元数据中的本机路径；题干、选项、答案、分类、稳定题号不变。模型输入JSONL、答案表、分集及必要原图逐字节保留。公开题库与CSV的元数据摘要重新计算，原本地摘要及映射见`public_export.json`。

历史实验报告中的哈希指向实际使用的本地原版；公开版仅改元数据，输入和答案哈希一致。报告不是在公开导出后重新调用模型生成的。云端模型响应不保证再次调用时逐字一致。

旧网页缓存、成员原始反馈附件、浏览器登录资料、密钥及原始模型请求响应未公开。现有公开数据可用于浏览、分析和重新评测；从全部原材料完整重建v0.3仍需要本机留存材料，不能声称仅本仓库即可重建整个采集历史。历史脚本和进度说明见`docs/local_progress_history.md`，部分链接仅在原工作区存在。

代码实现及数据修订有助手协助；变式由助手生成，成员提交与程序/助手修订分别记录。第三方题目与图片保留来源，不另行宣称拥有其版权或替其授予开源许可。本仓库未添加覆盖第三方材料的通用许可证。
''', encoding="utf-8")
    export_info = {
        "version": "public-export-v1", "source_manifest": {"sha256": sha(data / "manifest.json"), "questions_sha256": sha(data / "questions.jsonl"), "version": original_manifest["version"]},
        "public_manifest_sha256": public_manifest_hash,
        "public_inputs": manifest["inputs"], "source_inputs": original_manifest["inputs"],
        "public_answers": manifest["answers"], "source_answers": original_manifest["answers"],
        "core_question_fields_unchanged": True, "model_inputs_answers_and_images_byte_identical": True,
        "non_model_reviewer_labels_anonymized": len(private_labels),
        "reviewer_records_anonymized": sum(str(q.get("release_review", {}).get("reviewer_as_submitted")) in replacements for q in original),
        "api_config_caps_disabled": True,
        "omitted": ["API credentials", "browser login profiles", "original feedback archives", "raw HTTP/model logs", "legacy source caches and downloaded public datasets"],
        "historical_reports_scope": "Local original run; public metadata-only derivative is documented by this mapping.",
    }
    dump(DEST / "public_export.json", export_info)
    findings = []
    for path in DEST.rglob("*"):
        if not path.is_file(): continue
        raw = path.read_bytes()
        if any(value.encode() in raw for value in actual_keys): findings.append(path.relative_to(DEST).as_posix())
        if path.suffix.lower() in TEXT and any(name.encode() in raw for name in private_labels):
            findings.append(path.relative_to(DEST).as_posix())
    if findings:
        raise RuntimeError("Private value detected in export files: " + ", ".join(sorted(set(findings))))
    for section in ("inputs", "answers"):
        for entry in manifest[section].values():
            assert sha(data / entry["path"]) == sha(DEST / data_rel / entry["path"])
    assert sha(data / "questions.jsonl") == export_info["source_manifest"]["questions_sha256"]
    return {"destination": str(DEST), "questions": len(public_questions), "reviewer_records_anonymized": export_info["reviewer_records_anonymized"], "private_key_matches": 0, "public_manifest_sha256": public_manifest_hash}


if __name__ == "__main__":
    print(json.dumps(export(), ensure_ascii=False))
