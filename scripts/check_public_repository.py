#!/usr/bin/env python3
"""Read-only checks for a staged public EduMathBench repository."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

MAX_BYTES = 95 * 1024 * 1024
DEFAULT_REPORT = Path(__file__).resolve().parents[1] / "deliverables" / "public_repository_check.json"
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".jsonl", ".csv", ".html", ".js", ".ps1", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".xml", ".sql", ".sh"}
SUSPECTS = {
    "github_pat": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "live_secret": re.compile(r"\bsk-(?:live-)?[A-Za-z0-9_-]{20,}\b"),
    "private_key_pem": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
}
SAFE_CONTEXT = re.compile(r"synthetic|fixture|dummy|placeholder|example|fake|test[_ -]?key", re.I)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fail(report: dict, check: str, detail: str) -> None:
    report["failures"].append({"check": check, "detail": detail})


def rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, type=Path, help="staged public repository root")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = ap.parse_args()
    root = args.root.resolve()
    report_path = args.report.resolve()
    report = {"root": str(root), "passed": False, "failures": [], "credential_findings": [], "checks": {}}
    if not root.is_dir():
        fail(report, "root", "public repository root does not exist")
    else:
        files = [p for p in root.rglob("*") if p.is_file() and p.resolve() != report_path]
        bad_env = [p for p in files if p.name.lower().startswith(".env") and not (p.name.lower().endswith(".example") or p.name.lower().endswith(".template"))]
        if bad_env: fail(report, "env_files", ", ".join(rel(root,p) for p in bad_env))
        forbidden = re.compile(r"(^|/)(?:cookies?(?:\.sqlite)?|login data|web data|local state|\.local_browser_profile|\.profiles|browser_profiles?)(/|$)", re.I)
        bad_profiles = [p for p in files if forbidden.search(rel(root,p).replace("\\", "/"))]
        if bad_profiles: fail(report, "browser_credentials", ", ".join(rel(root,p) for p in bad_profiles[:30]))
        bad_dirs = [p for p in root.rglob("*") if p.is_dir() and p.name.lower() in {"node_modules", ".runtime_deps"}]
        if bad_dirs: fail(report, "dependency_caches", ", ".join(rel(root,p) for p in bad_dirs[:30]))
        oversized = [p for p in files if p.stat().st_size > MAX_BYTES]
        if oversized: fail(report, "file_size", ", ".join(f"{rel(root,p)} ({p.stat().st_size} bytes)" for p in oversized))
        archives = [p for p in files if p.suffix.lower() in {".zip", ".rar"}]
        if archives: fail(report, "archives", ", ".join(rel(root,p) for p in archives[:50]))
        report["checks"].update({"files_scanned": len(files), "env_files": len(bad_env), "browser_profile_files": len(bad_profiles), "dependency_cache_dirs": len(bad_dirs), "oversized_files": len(oversized), "archives": len(archives)})

        # Pattern-only scan. Findings never contain matched text.
        for p in files:
            if p.suffix.lower() not in TEXT_SUFFIXES or p.stat().st_size > 30 * 1024 * 1024:
                continue
            try:
                lines = p.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            except OSError:
                continue
            for n, line in enumerate(lines, 1):
                for kind, pattern in SUSPECTS.items():
                    for match in pattern.finditer(line):
                        token = match.group(0)
                        if kind != "private_key_pem" and (len(token) < 32 or SAFE_CONTEXT.search(line)):
                            continue
                        report["credential_findings"].append({"path": rel(root,p), "line": n, "type": kind})
        if report["credential_findings"]:
            fail(report, "credential_patterns", f"{len(report['credential_findings'])} possible credential pattern(s); see path/line/type findings")

        data = root / "data" / "benchmark_web_v0.3"
        manifest_path, questions_path, csv_path = data / "manifest.json", data / "questions.jsonl", data / "questions.csv"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            questions = [json.loads(line) for line in questions_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            if len(questions) != 1800: fail(report, "question_count", f"expected 1800 records, got {len(questions)}")
            if manifest.get("question_count", len(questions)) != len(questions): fail(report, "manifest_question_count", "manifest count differs from questions.jsonl")
            # Support the release manifest convention and the public-export extension.
            for key, path in (("questions", questions_path), ("csv", csv_path)):
                entry = manifest.get("public_release", {}).get(key) or manifest.get("public_export", {}).get(key) or manifest.get(key)
                if isinstance(entry, dict): expected = entry.get("sha256")
                elif isinstance(entry, str) and len(entry) == 64: expected = entry
                else: expected = None
                if expected and expected.lower() != sha(path): fail(report, f"{key}_sha256", f"manifest hash mismatch for {rel(root,path)}")
                if not expected: fail(report, f"{key}_sha256", f"manifest has no recognized hash for {key}")
            # Inputs and answers: every declared hash must match. Require all 4 splits.
            for section in ("inputs", "answers"):
                entries = manifest.get(section, {})
                if not isinstance(entries, dict) or not {"all","debug","dev","test"}.issubset(entries):
                    fail(report, f"{section}_manifest", f"manifest missing expected split entries")
                    continue
                for split, entry in entries.items():
                    p = data / entry.get("path", "")
                    if not p.is_file() or sha(p) != entry.get("sha256"):
                        fail(report, f"{section}_sha256", f"missing or mismatched {section}/{split}")
            # Asset references use sha256 and files in assets/input.
            missing_assets = 0
            for q in questions:
                for asset in q.get("image_assets", []):
                    digest = asset.get("sha256")
                    candidates = list((data / "assets" / "input").glob(f"{digest}.*")) if digest else []
                    if not any(p.is_file() and sha(p) == digest for p in candidates): missing_assets += 1
            if missing_assets: fail(report, "image_assets", f"{missing_assets} referenced image(s) missing or hash-mismatched")
            # public_export.json binds original source hashes to byte-identical public inputs.
            export_path = root / "public_export.json"
            if not export_path.is_file(): fail(report, "public_export", "public_export.json is missing")
            else:
                export = json.loads(export_path.read_text(encoding="utf-8-sig"))
                source = export.get("source_manifest", {})
                pubinputs = export.get("public_inputs", export.get("inputs", {}))
                for split in ("all", "debug", "dev", "test"):
                    entry = pubinputs.get(split) if isinstance(pubinputs, dict) else None
                    if not isinstance(entry, dict):
                        # Allow binding to paths in the current release manifest.
                        entry = manifest.get("inputs", {}).get(split)
                    if not isinstance(entry, dict):
                        fail(report, "public_export_inputs", f"no public input mapping for {split}"); continue
                    p = data / entry.get("path", "")
                    wanted = entry.get("sha256")
                    if not p.is_file() or not wanted or sha(p) != wanted:
                        fail(report, "public_export_inputs", f"public input hash mismatch for {split}")
                if not source: fail(report, "public_export_source_manifest", "source_manifest hashes missing")
                for section in ("inputs", "answers"):
                    originals = export.get("source_" + section, {})
                    published = export.get("public_" + section, {})
                    for split in ("all", "debug", "dev", "test"):
                        before = originals.get(split, {}).get("sha256")
                        after = published.get(split, {}).get("sha256")
                        if not before or before != after or after != manifest.get(section, {}).get(split, {}).get("sha256"):
                            fail(report, "public_export_byte_identity", f"source/public {section}/{split} hashes differ or are absent")
            # CSV's serialized full record must equal canonical JSONL records.
            with csv_path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            json_by_id = {q.get("id"): q for q in questions}
            record_col = next((c for c in ("record_json", "record") if rows and c in rows[0]), None)
            if not record_col:
                fail(report, "csv_record_json", "CSV has no record_json/record column")
            else:
                for row in rows:
                    try: obj = json.loads(row[record_col])
                    except (ValueError, TypeError): fail(report, "csv_record_json", "invalid serialized record"); break
                    if obj != json_by_id.get(obj.get("id")):
                        fail(report, "csv_record_json", "CSV record differs from canonical JSONL"); break
            report["checks"].update({"questions": len(questions), "referenced_images_missing": missing_assets, "csv_rows": len(rows)})
        except Exception as exc:
            fail(report, "data_integrity", f"could not complete data integrity checks ({type(exc).__name__})")
    report["passed"] = not report["failures"]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "failures": len(report["failures"]), "credential_findings": len(report["credential_findings"]), "report": str(report_path)}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
