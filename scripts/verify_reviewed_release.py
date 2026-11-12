"""Independent, offline integrity checks for the member-reviewed v0.3 release.

Writes only reports/release_validation.json. Reproduction builds run in temporary
directories with sockets disabled and never overwrite either released dataset.
The six submitted member reviews remain the accepted review basis.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "data/benchmark_web_v0.2"
OUT = ROOT / "data/benchmark_web_v0.3"
FEEDBACK = ROOT / "AI复核/反馈汇总_20261107"
REV = ROOT / "data/revisions_20261110"
sys.path.insert(0, str(ROOT / "scripts"))
from review_release_assets import assert_source_assets, input_fields

DATASET_PREFIXES = ("EMB-P-BULK-CMM-", "EMB-P-BULK-TAL-", "EMB-P-MATHBENCH-", "EMB-P-CEVAL-",
                    "EMB-P-CJEVAL-", "EMB-P-IMG-CMM-", "EMB-P-CMMA-")
INPUT_KEYS = {"id", "review_no", "grade", "module", "difficulty", "parent_id", "family_id", "question",
              "options", "image_assets", "split", "kind"}
ASSET_KEYS = {"path", "sha256", "mime_type", "field", "placeholder", "role"}
ASSET_ALIAS_KEYS = {"source_placeholder_field", "placeholder_index", "contains_answer_or_solution", "binding_origin"}
CONTENT_LEAK_RE = re.compile(r"【(?:答案|解析|解答)】|(?:参考答案|正确答案|答案解析|解析过程)\s*[:：]")


def read(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def sha(path: str | Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def tree_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def normalized_text(value: str) -> str:
    """Conservative visual normalization; numbers and mathematical signs remain."""
    value = unicodedata.normalize("NFKC", html.unescape(value))
    value = value.translate(str.maketrans({"−": "-", "–": "-", "—": "-", "。": ".", "，": ","}))
    value = re.sub(r"\\(?:left|right|quad|qquad|,|;|!)", "", value)
    for delimiter in ("$", r"\(", r"\)", r"\[", r"\]"):
        value = value.replace(delimiter, "")
    return re.sub(r"\s+", "", value)


def duplicate_groups(rows: list[dict[str, Any]]) -> dict[str, list[list[dict[str, Any]]]]:
    """Exact displayed inputs and long numeric templates, independently grouped."""
    exact, templates = defaultdict(list), defaultdict(list)
    for question in rows:
        by_placeholder = {asset["placeholder"]: asset["sha256"] for asset in question["image_assets"] if asset["placeholder"]}

        def content(value: str) -> str:
            for placeholder, digest in by_placeholder.items():
                value = value.replace(placeholder, "<image:" + digest + ">")
            return normalized_text(value)

        unplaced = tuple(sorted(a["sha256"] for a in question["image_assets"] if not a["placeholder"]))
        key = (content(question["question"]), tuple(sorted(content(v) for v in question["options"].values())), unplaced)
        exact[key].append(question)
        if not question["image_assets"]:
            template = re.sub(r"\d+(?:\.\d+)?", "<N>", normalized_text(question["question"]))
            if len(template) >= 35:
                templates[template].append(question)
    return {"exact": [group for group in exact.values() if len(group) > 1],
            "long_numeric_template": [group for group in templates.values() if len(group) > 1]}


def check_csv(output: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    with (output / "questions.csv").open(encoding="utf-8-sig", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    require([json.loads(q["record_json"]) for q in csv_rows] == rows, "CSV record_json differs from JSONL")
    for csv_question, question in zip(csv_rows, rows):
        for field in ("id", "question", "answer", "parent_id", "family_id", "split", "module", "difficulty"):
            require(csv_question[field] == question[field], f"CSV {field}: {question['id']}")
        for letter in "ABCD":
            require(csv_question["option_" + letter.lower()] == question["options"][letter], f"CSV option {letter}: {question['id']}")
    return {"records_roundtripped": len(csv_rows)}


def check_inputs(output: Path, rows: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    evidence = {}
    for split, predicate in (("all", lambda q: True), ("dev", lambda q: q["split"] == "dev"),
                             ("test", lambda q: q["split"] == "test"), ("debug", lambda q: q["debug_subset"])):
        subset = [q for q in rows if predicate(q)]
        inputs = read(output / f"inputs/{split}_inputs.jsonl")
        answers = read(output / f"answers/{split}_answers.jsonl")
        expected_ids = [q["id"] for q in subset]
        require([q["id"] for q in inputs] == expected_ids, f"{split} input IDs/order")
        require([q["id"] for q in answers] == expected_ids, f"{split} answer IDs/order")
        require((output / f"splits/{split}_ids.txt").read_text(encoding="utf-8").splitlines() == expected_ids,
                f"{split} ID text differs")
        for original, model_input, answer in zip(subset, inputs, answers):
            require(set(model_input) == INPUT_KEYS, f"Input contains prohibited/missing fields: {original['id']}")
            require(set(answer) == {"id", "answer"} and answer["answer"] == original["answer"], f"Answer isolation: {original['id']}")
            for field in INPUT_KEYS - {"kind", "image_assets"}:
                require(model_input[field] == original[field], f"Input {field} differs: {original['id']}")
            expected_assets = deepcopy(original["image_assets"])
            for asset in expected_assets:
                if asset["field"].startswith("option_"):
                    asset["field"] = "options." + asset["field"][-1].upper()
            require(model_input["image_assets"] == expected_assets, f"Input image field mapping differs: {original['id']}")
            require(model_input["kind"] == original["source_type"], f"Input kind differs: {original['id']}")
            require(not any(CONTENT_LEAK_RE.search(value) for value in input_fields(model_input).values()),
                    f"Answer/solution marker in input content: {original['id']}")
            require(all(ASSET_KEYS <= set(asset) <= ASSET_KEYS | ASSET_ALIAS_KEYS for asset in model_input["image_assets"]),
                    f"Image contains provenance/proof fields: {original['id']}")
        for kind in ("inputs", "answers"):
            entry = manifest[kind][split]
            require(entry["path"] == f"{kind}/{split}_{kind}.jsonl", f"Unexpected {split} {kind} path")
            require(entry["count"] == len(subset) and entry["sha256"] == sha(output / entry["path"]),
                    f"Manifest {split} {kind} hash/count")
        evidence[split] = {"count": len(subset), "inputs_sha256": manifest["inputs"][split]["sha256"],
                           "answers_sha256": manifest["answers"][split]["sha256"]}
    return evidence


def check_reproduction(output: Path) -> dict[str, Any]:
    protected_roots = {"v0.2": OLD, "feedback": FEEDBACK}
    before = {name: tree_hashes(path) for name, path in protected_roots.items()}
    outputs = []
    runner = """import pathlib, socket, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]) / 'scripts'))
def denied(*args, **kwargs):
    raise RuntimeError('Network disabled during release reproduction')
socket.create_connection = denied
socket.socket.connect = denied
socket.socket.connect_ex = denied
import build_reviewed_release as builder
builder.OUT = pathlib.Path(sys.argv[2])
builder.build()
"""
    with tempfile.TemporaryDirectory(prefix="edumath-release-replay-") as temporary:
        temporary_root = Path(temporary).resolve()
        for index in (1, 2):
            destination = temporary_root / f"run{index}"
            require(destination.is_relative_to(temporary_root), "Reproduction path escaped temporary root")
            result = subprocess.run([sys.executable, "-X", "utf8", "-c", runner, str(ROOT), str(destination)],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=180)
            require(result.returncode == 0, f"Offline builder run {index} failed: {result.stderr[-6000:]}")
            outputs.append(tree_hashes(destination))
        differences = sorted(key for key in outputs[0].keys() | outputs[1].keys() if outputs[0].get(key) != outputs[1].get(key))
        require(not differences, f"Builder runs differ: {differences[:20]}")
        shipped_differences = [key for key, digest in outputs[0].items() if not (output / key).is_file() or sha(output / key) != digest]
        require(not shipped_differences, f"Released core files differ from offline reproduction: {shipped_differences[:20]}")
    after = {name: tree_hashes(path) for name, path in protected_roots.items()}
    changed = {name: sorted(key for key in before[name].keys() | after[name].keys() if before[name].get(key) != after[name].get(key))
               for name in protected_roots}
    require(not any(changed.values()), f"Source/feedback changed during reproduction: {changed}")
    return {"runs": 2, "network_disabled": True, "comparison": "exact byte hashes, including all builder reports and assets",
            "generated_files_compared": len(outputs[0]), "core_hashes": {key: value for key, value in outputs[0].items()
                                                                        if not key.startswith("assets/")},
            "source_files_unchanged": {name: len(hashes) for name, hashes in before.items()}}


def verify(output_root: str | Path = OUT, reproduce: bool = True, write_report: bool = True) -> dict[str, Any]:
    output = Path(output_root)
    rows = read(output / "questions.jsonl")
    public = [q for q in rows if q["source_type"] == "public"]
    variants = [q for q in rows if q["source_type"] == "variant"]
    by_id = {q["id"]: q for q in rows}
    old = read(OLD / "questions.jsonl")
    old_by_id = {q["id"]: q for q in old}
    config = json.loads((ROOT / "config/quotas.json").read_text(encoding="utf-8"))
    variant_config = json.loads((ROOT / "config/variant_quotas.json").read_text(encoding="utf-8"))
    rebuild_config = json.loads((OLD / "rebuild_config.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    checks, issues, evidence = [], [], {}

    def check(name, function):
        try:
            result = function()
            checks.append({"name": name, "passed": True})
            if result is not None:
                evidence[name] = result
        except Exception as exc:
            checks.append({"name": name, "passed": False})
            issues.append({"name": name, "error": str(exc)})

    def counts():
        require((len(rows), len(public), len(variants), len(by_id)) == (1800, 1500, 300, 1800), "Expected 1800 unique=1500 public+300 variants")
        require(Counter(q["grade"] for q in public) == Counter({7: 500, 8: 500, 9: 500}), "Public grade counts")
        require(Counter(q["grade"] for q in variants) == Counter({7: 100, 8: 100, 9: 100}), "Variant grade counts")
        for questions, quota, label in ((public, config, "public"), (variants, variant_config, "variant")):
            expected = Counter({(c["grade"], c["module"]): c["target"] for c in quota["cells"] if c["target"]})
            require(Counter((q["grade"], q["module"]) for q in questions) == expected, label + " grade/module quota")
        require(Counter(q["difficulty"] for q in public) == Counter(config["difficulty_targets"]), "Public 600/600/300 quota")
        for question in rows:
            require(set(question["options"]) == set("ABCD") and all(question["options"].values()) and
                    question["answer"] in question["options"], "Invalid options/answer: " + question["id"])
            require(question["solution"] == "" and question["solution_format"] == "not_requested", "Solution included: " + question["id"])
        return {"total": len(rows), "public": len(public), "variants": len(variants),
                "public_difficulty": dict(Counter(q["difficulty"] for q in public)),
                "variant_difficulty_observed": dict(Counter(q["difficulty"] for q in variants)),
                "variant_difficulty_is_descriptive_not_an_enforced_margin": True}

    check("record_counts_and_exact_quotas", counts)

    def lineage():
        retained = {q["id"] for q in old if q.get("acquisition_origin") == "retained_legacy_web"}
        require(len(retained) == 363 and retained == {q["id"] for q in public if q.get("acquisition_origin") == "retained_legacy_web"}, "Retained 363 changed")
        require(Counter(q["acquisition_origin"] for q in public) == Counter({"retained_legacy_web": 363, "new_web_crawl": 1137}), "Public acquisition counts")
        require(not any(q["id"].startswith(DATASET_PREFIXES) for q in rows), "Public-dataset source ID returned")
        retired_ids = {q["id"] for q in read(OLD / "baseline/retired_public.jsonl")}
        require(not retired_ids & set(by_id), "Retired dataset source ID returned")
        for question in public:
            source = question["source"]
            parsed = urlparse(source["url"])
            require(parsed.scheme in {"http", "https"} and parsed.netloc and source["relation"] == "public_origin",
                    "Missing real web provenance: " + question["id"])
            raw = ROOT / source["raw_path"]
            require(raw.is_file(), "Missing archived source: " + str(raw))
            if question.get("acquisition_origin") == "new_web_crawl":
                require(sha(OLD / question["raw_path"]) == question["raw_sha256"] == question["lineage"]["raw_sha256"],
                        "New web raw/lineage hash: " + question["id"])
        return {"retained": 363, "new_web": 1137, "real_local_source_files": len({q["source"]["raw_path"] for q in public})}

    check("public_web_provenance_and_retained_ids", lineage)

    def splits():
        dev = [q for q in rows if q["split"] == "dev"]
        test = [q for q in rows if q["split"] == "test"]
        debug = [q for q in rows if q["debug_subset"]]
        require((len(dev), len(test), len(debug)) == (150, 1650, 100), "Dev/test/debug counts")
        require(Counter(q["grade"] for q in dev) == Counter({7: 50, 8: 50, 9: 50}), "Dev grades")
        require(all(q["source_type"] == "public" for q in dev) and {q["id"] for q in debug} <= {q["id"] for q in dev}, "Variant in dev or debug outside dev")
        protected_dev, protected_debug = set(rebuild_config["protected_dev_ids"]), set(rebuild_config["protected_debug_ids"])
        require(len(protected_dev) == 31 and protected_dev <= {q["id"] for q in dev}, "Protected dev31 lost")
        require(len(protected_debug) == 20 and protected_debug <= {q["id"] for q in debug}, "Protected debug20 lost")
        mothers = {q["parent_id"] for q in variants}
        require(len(mothers) == 300 and mothers <= {q["id"] for q in public}, "300 distinct public mothers")
        mother_families = {by_id[identifier]["family_id"] for identifier in mothers}
        require(all(q["split"] == "test" for q in rows if q["family_id"] in mother_families), "A mother family crosses out of test")
        require(all(q["family_id"] == by_id[q["parent_id"]]["family_id"] and q["split"] == "test" for q in variants), "Variant mother family binding")
        family_splits = defaultdict(set)
        for question in rows:
            family_splits[question["family_id"]].add(question["split"])
        require(all(len(value) == 1 for value in family_splits.values()), "A declared family crosses dev/test")
        groups = duplicate_groups(rows)
        leakage = [{"kind": kind, "ids": [q["id"] for q in group]} for kind, grouped in groups.items() for group in grouped
                   if len({q["split"] for q in group}) > 1]
        require(not leakage, "Independent near-duplicate grouping crosses split: " + json.dumps(leakage[:10], ensure_ascii=False))
        public_groups = duplicate_groups(public)
        require(all(len({q["family_id"] for q in group}) == 1 for grouped in public_groups.values() for group in grouped), "Duplicate public inputs have different families")
        return {"dev": 150, "test": 1650, "debug": 100, "protected_dev": 31, "protected_debug": 20, "distinct_mothers": 300,
                "independent_duplicate_groups": {kind: len(grouped) for kind, grouped in groups.items()}, "cross_split_groups": 0}

    check("protected_family_splits_and_independent_near_duplicates", splits)
    check("answer_free_inputs_and_separate_hashed_answers", lambda: check_inputs(output, rows, manifest))

    def images():
        original_hashes = {a["sha256"] for question in old for a in question["image_assets"]}
        cache = read(OLD / "candidates/eligible.jsonl")
        original_hashes.update(a["sha256"] for question in cache for a in question.get("image_assets", [])
                               if a.get("role") not in {"answer", "solution"} and a.get("sha256"))
        actual_hashes = set()
        for question in rows:
            require(question["input_modality"] == ("text_image" if question["image_assets"] else "text"), "Modality mismatch: " + question["id"])
            for index, asset in enumerate(question["image_assets"]):
                require(ASSET_KEYS <= set(asset) <= ASSET_KEYS | ASSET_ALIAS_KEYS and asset["role"] in {"stem", "option"}, "Non-input image metadata: " + question["id"])
                require(asset["path"].startswith("assets/input/") and asset["sha256"] in original_hashes, "Image not an archived original asset: " + question["id"])
                require(asset.get("source_placeholder_field", asset["field"]) == asset["field"], "Image field alias mismatch: " + question["id"])
                require(asset.get("placeholder_index", index) == index and asset.get("contains_answer_or_solution", False) is False,
                        "Image occurrence alias/answer contamination: " + question["id"])
                require(asset["placeholder"], "Missing required runner image marker: " + question["id"])
                if "binding_origin" in asset:
                    require(asset["binding_origin"] == "explicit_marker_for_original_unplaced_figure" and
                            asset["placeholder"] == "[图片:" + asset["sha256"][:16] + "]", "Restored figure marker provenance mismatch: " + question["id"])
                from PIL import Image
                with Image.open(output / asset["path"]) as image:
                    require(asset["mime_type"] == Image.MIME.get(image.format), "Image MIME type mismatch: " + question["id"])
                actual_hashes.add(asset["sha256"])
            assert_source_assets(question, output)
        screenshots = list((ROOT / "AI复核/AI复核数据_1800题_20261023").rglob("*.png"))
        require(len(screenshots) == 619, "Expected exactly619 original review screenshots")
        audit_hashes = {sha(path) for path in (ROOT / "AI复核").rglob("*.png")}
        require(not actual_hashes & audit_hashes, "Whole-question review screenshots entered model inputs")
        return {"occurrences": sum(len(q["image_assets"]) for q in rows), "distinct_original_files": len(actual_hashes),
                "original_screenshots_excluded": len(screenshots), "all_unique_review_png_hashes_excluded": len(audit_hashes)}

    check("original_image_hashes_field_placeholder_and_no_review_screenshots", images)
    check("CSV_full_record_and_fields_roundtrip", lambda: check_csv(output, rows))

    def source_immutability():
        source_build = manifest["source_build"]
        paths = {"old_questions_sha256": OLD / "questions.jsonl", "feedback_sha256": FEEDBACK / "合并草稿/questions.jsonl",
                 "math_resolutions_sha256": REV / "math_resolutions.jsonl", "reserve_audit_sha256": REV / "reserve_audit.jsonl"}
        for key, path in paths.items():
            require(sha(path) == source_build[key], "Source build hash changed: " + key)
        original_feedback = json.loads((FEEDBACK / "合并草稿/manifest.json").read_text(encoding="utf-8"))
        require(original_feedback["source_questions_sha256"] == sha(OLD / "questions.jsonl"), "v0.2 changed since original feedback assembly")
        intake = json.loads((FEEDBACK / "intake_manifest.json").read_text(encoding="utf-8"))
        files = 0
        for archive in intake["archives"]:
            require(sha(archive["archive"]) == archive["archive_sha256"], "Original submitted ZIP changed: " + archive["archive"])
            for entry in archive["files"]:
                path = Path(archive["extracted_directory"]) / entry["path"]
                require(path.stat().st_size == entry["size"] and sha(path) == entry["sha256"], "Original feedback file changed: " + str(path))
                files += 1
        require(len(intake["archives"]) == 6, "Expected six original feedback ZIPs")
        require(manifest["questions_sha256"] == sha(output / "questions.jsonl") and manifest["csv_sha256"] == sha(output / "questions.csv"), "Release manifest data hashes")
        return {"original_archives_verified": len(intake["archives"]), "original_extracted_files_verified": files,
                "source_build_hashes": {key: sha(path) for key, path in paths.items()}}

    check("original_sources_feedback_and_release_manifest_unchanged", source_immutability)

    def reserve_sources():
        added = read(output / "history/added_cached_questions.jsonl")
        eligible = {q["id"]: q for q in read(OLD / "candidates/eligible.jsonl")}
        audit = {q["id"]: q for q in read(REV / "reserve_audit.jsonl")}
        expected_additions=manifest['source_build']['added_from_existing_crawler_cache']
        require(len(added) == expected_additions and len({q["id"] for q in added}) == expected_additions, "Distinct cache addition count disagrees with release build and active IDs")
        require({q["id"] for q in added} == {q["id"] for q in rows if q["id"] not in old_by_id}, "Cache additions history mismatch")
        details = []
        for item in added:
            identifier = item["id"]
            question, source = by_id[identifier], eligible[identifier]
            require(audit[identifier]["usable"] is True, "Selected unusable cache item: " + identifier)
            require(all(question[field] == source[field] for field in ("question", "options", "answer", "grade", "module", "difficulty")), "Cache content/label changed: " + identifier)
            raw = OLD / source["raw_path"]
            digest = sha(raw)
            require(digest == source["raw_sha256"] == source["lineage"]["raw_sha256"] == question["raw_sha256"], "Cache raw SHA mismatch: " + identifier)
            require((ROOT / question["source"]["raw_path"]).resolve() == raw.resolve(), "Cache source path mismatch: " + identifier)
            require(question["source"]["url"] == source["source_url"] and question["source"]["reference"] == source["source_question_id"], "Cache source URL/reference mismatch: " + identifier)
            require(urlparse(question["source"]["url"]).hostname == "www.tiku.cn", "Unexpected cache source domain: " + identifier)
            text = raw.read_text(encoding="utf-8-sig")
            require(re.search(r'\bid\s*=\s*[\"\']p' + re.escape(source["source_question_id"]) + r'[\"\']', text), "Source HTML native ID missing: " + identifier)
            visible = html.unescape(re.sub(r"<[^>]+>", " ", text))
            answers = re.findall(r"答案\s*[:：]\s*([A-D])", visible)
            require(answers and set(answers) == {question["answer"]}, "HTML explicit answer mismatch: " + identifier)
            review = question["release_review"]
            require(review["status"] == "program_checked_cached_replacement" and review["member_review_claimed"] is False, "Cache falsely claims member review: " + identifier)
            details.append({"id": identifier, "raw_sha256": digest, "source_answer": question["answer"]})
        return {"count": len(details), "all_program_checked_not_member_review_claimed": True, "records": details}

    check("cached_additions_have_original_HTML_and_explicit_answer_evidence", reserve_sources)

    def repairs():
        from verify_web_variant_math import check_spec
        repaired_ids = {"EMB-V-WEB2R2-G8-126", "EMB-V-WEB2R2-G8-131", "EMB-V-WEB2R2-G8-183"}
        require({q["id"] for q in rows if q["release_review"]["status"] == "assistant_repaired_variant_program_verified"} == repaired_ids, "Unexpected new assistant repairs")
        details = []
        for identifier in sorted(repaired_ids):
            question = by_id[identifier]
            answers, detail = check_spec(question["verification_spec"])
            require(answers == [question["answer"]], "Repaired variant spec answer: " + identifier)
            require(question["release_review"]["member_review_claimed"] is False and question["generation_metadata"]["parent_id"] == question["parent_id"], "Repair provenance: " + identifier)
            predecessor = question["post_member_resolution"]["predecessor"]
            require(question["question"] != predecessor["question"] and question["options"] != predecessor["options"], "Repair was not a real content rewrite: " + identifier)
            details.append({"id": identifier, "answer": answers[0], "program_evidence": detail})
        require(by_id["EMB-V-WEB2R2-G8-183"]["parent_id"] == "EMB-P-G8-000006", "Variant183 new mother")
        paired = [q for q in rows if q.get("review_no") in {816, 875}]
        require(len(paired) == 2 and len({q["family_id"] for q in paired}) == 1 and all(q["split"] == "dev" for q in paired), "Protected816 / old mother875 near-duplicate repair")
        return {"three_actual_rewrites_verified": details, "review_816_and_875_same_dev_family": True,
                "member_reviewed_user_confirmed_count": sum(q["release_review"]["status"] == "member_reviewed_user_confirmed" for q in rows),
                "new_human_review_assigned": False}

    check("three_rewritten_variants_and_protected_duplicate_repair", repairs)
    if reproduce:
        check("offline_builder_reproduces_twice_and_leaves_sources_unchanged", lambda: check_reproduction(output))
    else:
        checks.append({"name": "offline_builder_reproduces_twice_and_leaves_sources_unchanged", "passed": None, "skipped": True})

    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "data_sha256": sha(output / "questions.jsonl"),
              "passed": not issues and reproduce, "checks": checks, "issues": issues, "evidence": evidence,
              "review_basis": "User confirmed six submitted member-reviewed parts; existing review accepted.",
              "validation_scope": "Offline program checks, source/answer integrity and deterministic reproduction; no new human review tasks.",
              "new_human_review_assigned": False, "network_requests": 0}
    if write_report:
        path = output / "reports/release_validation.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--skip-reproduce", action="store_true", help="Run static checks only; report will not claim a full pass")
    args = parser.parse_args()
    report = verify(args.output, reproduce=not args.skip_reproduce)
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]), "issues": report["issues"]}, ensure_ascii=False))
    if report["issues"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
