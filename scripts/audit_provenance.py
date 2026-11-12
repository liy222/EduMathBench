"""Read-only literal provenance audit for the current public draft."""
import collections
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "data/public_draft/questions.jsonl"
REPORT_JSON = ROOT / "data/reports/provenance_audit.json"
REPORT_MD = ROOT / "data/reports/provenance_audit.md"
DATASET_BATCHES = {
    "bulk_001", "bulk_cmm_supplement_001", "bulk_mathbench_001",
    "bulk_cjeval_001", "bulk_ceval_001",
    "hard_cmm_images_001",
    "hard_cmmath_001", "hard_reserve_001",
}
LINE_CACHE = {}
CEVAL_ID_CACHE = {}


def read_jsonl(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8-sig").splitlines() if s.strip()]


def resolve_path(value):
    return (ROOT / Path(value)).resolve() if value else None


def raw_lines(path):
    key = str(path)
    if key not in LINE_CACHE:
        LINE_CACHE[key] = path.read_text(encoding="utf-8-sig").splitlines()
    return LINE_CACHE[key]


def cmm_options(value):
    matches = list(re.finditer(r"(?:^|\n)\s*([A-F])\s*[.．、:：)）]\s*", value or ""))
    if [m.group(1) for m in matches] != list("ABCD"):
        return None
    return [value[m.end():matches[i + 1].start() if i < 3 else len(value)].strip()
            for i, m in enumerate(matches)]


def cjeval_split(content):
    markers = list(re.finditer(r"选项\s*[:：]", content or ""))
    if not markers:
        return None, None
    marker = markers[-1]
    stem, options = content[:marker.start()].strip(), content[marker.end():]
    bullets = list(re.finditer(r"(?<![A-Za-z])([A-D])[.．、:：]\s*", options))
    if len(bullets) != 4 or set(m.group(1) for m in bullets) != set("ABCD"):
        return stem, None
    by_label = {m.group(1): options[m.end():bullets[i + 1].start() if i < 3 else len(options)].strip()
                for i, m in enumerate(bullets)}
    return stem, [by_label[c] for c in "ABCD"]


def compare(q, stem, options, answer):
    differences = []
    expected = [("question", stem)]
    if options is None or len(options) != 4:
        differences.append("source_options_parse_uncertain")
    else:
        expected.extend((f"option_{c}", option) for c, option in zip("abcd", options))
    expected.append(("answer", answer))
    for field, value in expected:
        if str(q.get(field, "")) != str(value if value is not None else ""):
            differences.append(field)
    return differences


def parse_cmm_supplement_provenance(q):
    if not (q.get('source_id', '').startswith('SRC-BULK-CMM') or q.get('id', '').startswith('EMB-P-BULK-CMM')):
        return None
    match = re.search(r"第(\d+)行；原ID=([^；]+)", q.get("source_ref", ""))
    if not match:
        return None
    return {
        "dataset": "ecnu-icalk/cmm-math", "line": int(match.group(1)),
        "original_id": match.group(2), "local_path": q.get("source_raw_path"),
    }


def locate_record(q):
    provenance = q.get("provenance") or parse_cmm_supplement_provenance(q) or {}
    dataset = provenance.get("dataset", "")
    source_id = q.get("source_id", "")
    if not dataset and source_id.startswith("SRC-MATHBENCH"):
        dataset = "MathBench"
    path = resolve_path(provenance.get("local_path") or q.get("source_raw_path"))
    if path is None or not path.is_file():
        return None, path, "missing_raw_file", None
    kind = None
    if dataset == 'lizhongzhi2022/cmmath':
        key = str(path)
        if key not in CEVAL_ID_CACHE:
            CEVAL_ID_CACHE[key] = json.loads(path.read_text(encoding='utf-8'))
        index = provenance.get('array_index')
        data = CEVAL_ID_CACHE[key]
        if not isinstance(index, int) or not 0 <= index < len(data):
            return None, path, 'source_record_not_found', None
        record = data[index]
        if record.get('problem_id') != provenance.get('original_id'):
            return record, path, 'line_or_id_mismatch', index+1
        return record, path, 'cmmath', index+1
    if "cmm-math" in dataset:
        kind = "cmm"
    elif "TAL-SCQ5K" in dataset:
        kind = "tal"
    elif dataset == "MathBench":
        kind = "mathbench"
    elif q.get("batch_id") == "bulk_cjeval_001" or "CJEVAL" in source_id:
        kind = "cjeval"
    elif q.get("batch_id") == "bulk_ceval_001" or "CEVAL" in source_id:
        kind = "ceval"
    if kind is None:
        return None, path, "unmapped", None
    lines = raw_lines(path)
    line_no = provenance.get("line")
    if line_no is None:
        ref_match = re.search(r"第(\d+)行", q.get("source_ref", ""))
        if ref_match:
            line_no = int(ref_match.group(1))
    if kind == "ceval":
        source_record = (provenance.get("original_record") or {})
        wanted_id = source_record.get("id")
        key = str(path)
        if key not in CEVAL_ID_CACHE:
            CEVAL_ID_CACHE[key] = {}
            for line_index, line in enumerate(lines, 1):
                if line.strip():
                    candidate = json.loads(line)
                    CEVAL_ID_CACHE[key][str(candidate.get("id"))] = (candidate, line_index)
        found = CEVAL_ID_CACHE[key].get(str(wanted_id))
        if found:
            return found[0], path, kind, found[1]
        return None, path, "source_record_not_found", line_no
    if not isinstance(line_no, int) or line_no < 1 or line_no > len(lines):
        return None, path, "source_line_out_of_range", line_no
    record = json.loads(lines[line_no - 1])
    expected_id = provenance.get("original_id")
    if kind == "cjeval":
        expected_id = None  # CJEval provenance uses source row ordinal, recorded in the stable question id.
        qid_match = re.search(r"-(\d{6})$", q.get("id", ""))
        if qid_match and int(qid_match.group(1)) != line_no:
            return record, path, "line_or_id_mismatch", line_no
    elif expected_id is not None:
        actual_id = record.get("id") if kind == "cmm" else record.get("queId")
        if str(actual_id) != str(expected_id):
            return record, path, "line_or_id_mismatch", line_no
    return record, path, kind, line_no


def compare_record(q, record, kind):
    if record is None:
        return ["source_record_not_found"]
    if kind == "cmm":
        return compare(q, record.get("question"), cmm_options(record.get("options")), record.get("answer"))
    if kind == 'cmmath':
        original=record.get('question','')
        markers=list(re.finditer(r'(?m)^\s*([A-F])\s*[.．、:：]\s*',original))
        if [m.group(1) for m in markers] != list('ABCD'):
            return ['source_options_parse_uncertain']
        stem=original[:markers[0].start()].strip()
        options=[original[m.end():markers[i+1].start() if i<3 else len(original)].strip() for i,m in enumerate(markers)]
        return compare(q,stem,options,str(record.get('answer','')).strip())
    if kind == "tal":
        choices = [o[0].get("content", "") for o in record.get("answer_option_list", [])]
        return compare(q, record.get("problem"), choices, record.get("answer_value"))
    if kind == "mathbench":
        return compare(q, record.get("question"), record.get("options"), record.get("answer"))
    if kind == "cjeval":
        stem, choices = cjeval_split(record.get("ques_content", ""))
        answers = record.get("ques_answer", [])
        answer = answers[0] if len(answers) == 1 and answers[0] in list("ABCD") else "pending"
        return compare(q, stem, choices, answer)
    if kind == "ceval":
        return compare(q, record.get("question"), [record.get(c, "") for c in "ABCD"], record.get("answer"))
    return ["unmapped_source"]


def source_content(record, kind):
    if kind == "cmm":
        return record.get("question"), cmm_options(record.get("options")), record.get("answer")
    if kind == "tal":
        choices = [o[0].get("content", "") for o in record.get("answer_option_list", [])]
        return record.get("problem"), choices, record.get("answer_value")
    if kind == "mathbench":
        return record.get("question"), record.get("options"), record.get("answer")
    if kind == "cjeval":
        stem, choices = cjeval_split(record.get("ques_content", ""))
        answers = record.get("ques_answer", [])
        answer = answers[0] if len(answers) == 1 and answers[0] in list("ABCD") else "pending"
        return stem, choices, answer
    if kind == "ceval":
        return record.get("question"), [record.get(c, "") for c in "ABCD"], record.get("answer")
    return None, None, None


def compare_additional(parent, record, kind):
    stem, choices, answer = source_content(record, kind)
    differences = []
    if choices is None or len(choices) != 4:
        differences.append("source_options_parse_uncertain")
        return differences
    if str(parent.get("question", "")) != str(stem if stem is not None else ""):
        differences.append("question")
    if sorted(str(parent.get("option_" + c, "")) for c in "abcd") != sorted(str(x) for x in choices):
        differences.append("option_set")
    parent_answer = parent.get("option_" + str(parent.get("answer", "")).lower(), "")
    source_answer = choices["ABCD".index(answer)] if answer in "ABCD" and len(answer) == 1 else ""
    if str(parent_answer) != str(source_answer):
        differences.append("answer_option_text")
    return differences


def nonempty(s):
    return bool(str(s or "").strip())


def main():
    rows = read_jsonl(DRAFT)
    draft_sha256 = hashlib.sha256(DRAFT.read_bytes()).hexdigest()
    candidate_by_id = {}
    candidate_files = list((ROOT / "data/batches").glob("*/questions.jsonl")) + [
        ROOT / "data/bulk_prepared/all_candidates.jsonl",
        ROOT / "data/mathbench_prepared/all_candidates.jsonl",
        ROOT / "data/cjeval_work/inventory.jsonl",
    ]
    for candidate_file in candidate_files:
        if candidate_file.is_file():
            for candidate in read_jsonl(candidate_file):
                candidate_by_id[candidate.get("id")] = candidate
    batch_counts = collections.Counter(q.get("batch_id", "") for q in rows)
    metadata_issues = []
    for q in rows:
        missing = [field for field in ("source_title", "source_url", "source_ref", "source_raw_path")
                   if not nonempty(q.get(field))]
        raw_path = resolve_path(q.get("source_raw_path"))
        if raw_path is None or not raw_path.is_file():
            missing.append("source_raw_path_not_found")
        if missing:
            metadata_issues.append({"id": q.get("id"), "batch_id": q.get("batch_id"),
                                    "source_id": q.get("source_id"), "issues": missing})

    records = []
    for q in rows:
        if q.get("batch_id") not in DATASET_BATCHES:
            continue
        record, path, kind, line_no = locate_record(q)
        if kind in {"missing_raw_file", "source_line_out_of_range", "line_or_id_mismatch",
                    "source_record_not_found", "unmapped"}:
            records.append({"id": q.get("id"), "batch_id": q.get("batch_id"), "kind": kind,
                            "path": str(path) if path else q.get("source_raw_path"), "line": line_no})
            continue
        differences = compare_record(q, record, kind)
        provenance = q.get("provenance") or parse_cmm_supplement_provenance(q) or {}
        record_entry = {"id": q.get("id"), "batch_id": q.get("batch_id"), "kind": kind,
                        "path": str(path), "line": line_no,
                        "original_id": provenance.get("original_id") or
                                       (provenance.get("original_record") or {}).get("id"),
                        "differences": differences}
        if differences:
            record_entry["draft_fields"] = {f: q.get(f) for f in ["question", "option_a", "option_b", "option_c", "option_d", "answer"]}
            record_entry["source_fields"] = {
                "question": record.get("question") if kind != "tal" else record.get("problem"),
                "options": cmm_options(record.get("options")) if kind == "cmm" else
                           ([o[0].get("content", "") for o in record.get("answer_option_list", [])] if kind == "tal" else
                            record.get("options") if kind == "mathbench" else
                            ([record.get(c, "") for c in "ABCD"] if kind == "ceval" else
                             cjeval_split(record.get("ques_content", ""))[0:2])),
                "answer": record.get("answer") if kind in {"cmm", "mathbench", "ceval"} else
                          record.get("answer_value") if kind == "tal" else record.get("ques_answer"),
            }
        records.append(record_entry)

    # Check merged alternate source records retained on dataset questions as well.
    additional_count = 0
    additional_issues = []
    additional_unmapped_count = 0
    additional_metadata_issues = []
    for q in rows:
        for extra in q.get("additional_sources", []) or []:
            additional_count += 1
            extra_missing = [field for field in ("source_title", "source_url", "source_ref", "source_raw_path")
                             if not nonempty(extra.get(field))]
            extra_path = resolve_path(extra.get("source_raw_path"))
            if extra_path is None or not extra_path.is_file():
                extra_missing.append("source_raw_path_not_found")
            if extra_missing:
                additional_metadata_issues.append({"parent_id": q.get("id"), "id": extra.get("id"),
                                                   "issues": extra_missing})
            record, path, kind, line_no = locate_record(extra)
            if kind == "unmapped":
                additional_unmapped_count += 1
                continue
            if kind in {"missing_raw_file", "source_line_out_of_range", "line_or_id_mismatch",
                        "source_record_not_found", "unmapped"}:
                additional_issues.append({"parent_id": q.get("id"), "id": extra.get("id"), "kind": kind,
                                          "path": str(path) if path else extra.get("source_raw_path"),
                                          "line": line_no})
            else:
                original_candidate = candidate_by_id.get(extra.get("id"))
                differences = compare_record(original_candidate, record, kind) if original_candidate else compare_additional(q, record, kind)
                if differences:
                    additional_issues.append({"parent_id": q.get("id"), "id": extra.get("id"),
                                              "kind": kind, "path": str(path), "line": line_no,
                                              "candidate_available": original_candidate is not None,
                                              "differences": differences})

    mismatches = [r for r in records if r.get("differences") or r.get("kind") in {
        "missing_raw_file", "source_line_out_of_range", "line_or_id_mismatch",
        "source_record_not_found", "unmapped"}]
    kind_counts = collections.Counter(r["kind"] for r in records)
    web_spot_ids = {
        "EMB-P-WEB-FRACEQ4-JJ2019-7": {"pages": [10, 11], "source_answer": "D"},
        "EMB-P-WEB-FRACEQ4-JJ2019-8": {"pages": [11], "source_answer": "C"},
        "EMB-P-WEB-FRACEQ4-JJ2019-10": {"pages": [12], "source_answer": "D"},
    }
    present_ids = {q.get("id") for q in rows}
    web_spot_check = [{"id": qid, **details, "present_in_draft": qid in present_ids}
                      for qid, details in web_spot_ids.items()]
    summary = {
        "draft_path": str(DRAFT), "draft_question_count": len(rows),
        "draft_sha256": draft_sha256,
        "batch_counts": dict(batch_counts), "dataset_record_count": len(records),
        "dataset_counts_by_kind": dict(kind_counts),
        "literal_field_mismatches": len(mismatches),
        "metadata_issue_count": len(metadata_issues),
        "additional_source_count": additional_count,
        "additional_source_unmapped_count": additional_unmapped_count,
        "additional_source_issue_count": len(additional_issues),
        "additional_source_metadata_issue_count": len(additional_metadata_issues),
        "manual_web_batch_spot_check": {
            "batch_id": "bulk_fraction_equations_web_004",
            "checked_records": web_spot_check,
            "method": "visual comparison against archived source_page PNGs; not counted in dataset literal-comparison totals",
        },
        "scope": "逐题source对应是文本转换核对，不是数学正确性审核。未联网，未调用模型。",
        "records": records, "metadata_issues": metadata_issues,
        "additional_source_issues": additional_issues,
        "additional_source_metadata_issues": additional_metadata_issues,
    }
    REPORT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Provenance source correspondence audit", "",
             f"Draft snapshot: `{DRAFT.relative_to(ROOT)}` ({len(rows)} questions).",
             f"SHA-256: `{draft_sha256}`.",
             f"Dataset rows literally compared: {len(records)}; mismatches or unresolved mappings: {len(mismatches)}.",
             f"Raw source metadata/path issues across the full draft: {len(metadata_issues)}.",
             f"Merged additional source metadata/path issues: {len(additional_metadata_issues)}.",
             f"Merged additional source records checked: {additional_count - additional_unmapped_count}; issues: {len(additional_issues)}; other source types without dataset row locators: {additional_unmapped_count}.", "",
             "Comparison used archived local raw rows, provenance line/id, and the conversion rules in the extraction scripts. Fields checked: stem, four options, and source answer.",
             "逐题source对应是文本转换核对，不是数学正确性审核。未联网，未重新调用模型。", "",
             "## Public web batch spot check", "",
             "Visually checked the current batch 004 entries against archived PDF page images; this sample is not included in the dataset-row literal-comparison count.",
             "- Question 7: printed pages 10–11; source answer D; stem/options and answer label match the saved question.",
             "- Question 8: printed page 11; source answer C; stem/options and answer label match the saved question.",
             "- Question 10: printed page 12; source answer D; stem/options and answer label match the saved question.", "",
             "## Dataset coverage", ""]
    for kind, count in sorted(kind_counts.items()):
        lines.append(f"- {kind}: {count}")
    lines += ["", "## Mismatches or unresolved records", ""]
    if mismatches:
        for item in mismatches:
            lines.append(f"- `{item.get('id')}` ({item.get('batch_id')}): {item.get('kind') or ', '.join(item.get('differences', []))}; source line {item.get('line')}.")
    else:
        lines.append("- None in the records that could be mapped.")
    lines += ["", "## Metadata and raw path issues", ""]
    if metadata_issues:
        for item in metadata_issues:
            lines.append(f"- `{item['id']}` ({item['batch_id']}): {', '.join(item['issues'])}.")
    else:
        lines.append("- None; every draft row has a nonempty source title, URL, source reference/location, and existing raw path.")
    lines += ["", "## Additional source issues", ""]
    if additional_issues:
        for item in additional_issues:
            lines.append(f"- `{item.get('id')}` on `{item.get('parent_id')}`: {item.get('kind') or ', '.join(item.get('differences', []))}.")
    else:
        lines.append("- None.")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ["draft_question_count", "batch_counts", "dataset_record_count",
              "dataset_counts_by_kind", "literal_field_mismatches", "metadata_issue_count",
              "additional_source_count", "additional_source_issue_count"]}, ensure_ascii=True))
    if mismatches:
        for item in mismatches:
            print(json.dumps(item, ensure_ascii=True))


if __name__ == "__main__":
    main()
