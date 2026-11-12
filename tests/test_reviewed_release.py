"""Verifier checks catch independent leakage and exported-content corruption."""
from __future__ import annotations

import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_reviewed_release as verify


def question(identifier="one", split="dev"):
    return {"id": identifier, "question": "解分式方程2/(x−1)−3/x=0，正确的解是（ ）",
            "options": {"A": "x=3", "B": "x=2", "C": "x=1", "D": "x=−3"},
            "answer": "A", "parent_id": "", "family_id": "family", "split": split,
            "module": "方程与不等式", "difficulty": "中等", "image_assets": []}


class ReviewedReleaseVerifierTests(unittest.TestCase):
    def test_independent_normalization_catches_known_minus_sign_duplicate(self):
        first, second = question(), question("two", "test")
        second["question"] = second["question"].replace("−", "-")
        second["options"]["D"] = "x=-3"
        groups = verify.duplicate_groups([first, second])
        self.assertEqual(len(groups["exact"]), 1)
        self.assertEqual({q["split"] for q in groups["exact"][0]}, {"dev", "test"})

    def test_image_content_prevents_unrelated_figure_duplicates(self):
        first, second = question(), question("two")
        first["question"] = second["question"] = "如图，[图片:figure]，求角度"
        first["image_assets"] = [{"placeholder": "[图片:figure]", "sha256": "one"}]
        second["image_assets"] = [{"placeholder": "[图片:figure]", "sha256": "two"}]
        self.assertEqual(verify.duplicate_groups([first, second])["exact"], [])

    def test_equivalent_placeholder_ids_use_image_hash(self):
        first, second = question(), question("two")
        first["question"], second["question"] = "求[图片:one]的值", "求[图片:two]的值"
        first["image_assets"] = [{"placeholder": "[图片:one]", "sha256": "same"}]
        second["image_assets"] = [{"placeholder": "[图片:two]", "sha256": "same"}]
        self.assertEqual(len(verify.duplicate_groups([first, second])["exact"]), 1)

    def test_short_generic_stems_do_not_form_numeric_template_families(self):
        first, second = question(), question("two")
        first["question"], second["question"] = "求2+3", "求4+5"
        self.assertEqual(verify.duplicate_groups([first, second])["long_numeric_template"], [])

    def test_CSV_full_record_and_visible_columns_are_both_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            original = question()
            fields = ["id", "question", "answer", "parent_id", "family_id", "split", "module", "difficulty",
                      "option_a", "option_b", "option_c", "option_d", "record_json"]
            row = {field: original.get(field, "") for field in fields}
            row.update({"option_" + key.lower(): value for key, value in original["options"].items()})
            row["record_json"] = json.dumps(original, ensure_ascii=False)

            def write_csv():
                with (output / "questions.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow(row)

            write_csv()
            self.assertEqual(verify.check_csv(output, [original])["records_roundtripped"], 1)
            row["option_a"] = "tampered visible choice"
            write_csv()
            with self.assertRaisesRegex(AssertionError, "CSV option"):
                verify.check_csv(output, [original])
            row["option_a"] = original["options"]["A"]
            row["record_json"] = json.dumps({**original, "answer": "D"})
            write_csv()
            with self.assertRaisesRegex(AssertionError, "record_json"):
                verify.check_csv(output, [original])

    def test_input_content_leak_marker_detects_solution_headers(self):
        self.assertTrue(verify.CONTENT_LEAK_RE.search("问题。【解析】由公式得"))
        self.assertFalse(verify.CONTENT_LEAK_RE.search("下列问题的答案中，正确的是（ ）"))

    def test_input_option_field_mapping_allows_safe_aliases_but_rejects_proofs(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            original = question()
            original.update(review_no=1, grade=7, debug_subset=True, source_type="public")
            original["image_assets"] = [{"path": "assets/input/example.png", "sha256": "a" * 64,
                                         "mime_type": "image/png", "field": "option_a", "placeholder": "[图片:test]",
                                         "role": "option", "source_placeholder_field": "option_a", "placeholder_index": 0,
                                         "contains_answer_or_solution": False}]
            manifest = {"inputs": {}, "answers": {}}

            def write_exports(proof=False):
                for split in ("all", "dev", "test", "debug"):
                    subset = [] if split == "test" else [original]
                    model_inputs = []
                    for row in subset:
                        model_input = {key: copy.deepcopy(row[key]) for key in verify.INPUT_KEYS - {"kind"}}
                        model_input["kind"] = "public"
                        model_input["image_assets"][0]["field"] = "options.A"
                        if proof:
                            model_input["verification_spec"] = {"answer": "A"}
                        model_inputs.append(model_input)
                    keys = [{"id": row["id"], "answer": row["answer"]} for row in subset]
                    for kind, entries in (("inputs", model_inputs), ("answers", keys)):
                        relative = f"{kind}/{split}_{kind}.jsonl"
                        path = output / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in entries), encoding="utf-8")
                        manifest[kind][split] = {"path": relative, "sha256": verify.sha(path), "count": len(entries)}
                    path = output / f"splits/{split}_ids.txt"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("".join(row["id"] + "\n" for row in subset), encoding="utf-8")

            write_exports()
            self.assertEqual(verify.check_inputs(output, [original], manifest)["all"]["count"], 1)
            write_exports(proof=True)
            with self.assertRaisesRegex(AssertionError, "prohibited/missing fields"):
                verify.check_inputs(output, [original], manifest)

    def test_tree_hashes_detects_modified_and_added_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source.txt").write_text("original", encoding="utf-8")
            before = verify.tree_hashes(root)
            (root / "source.txt").write_text("changed", encoding="utf-8")
            (root / "new.txt").write_text("new", encoding="utf-8")
            after = verify.tree_hashes(root)
            self.assertNotEqual(before["source.txt"], after["source.txt"])
            self.assertIn("new.txt", after)


if __name__ == "__main__":
    unittest.main()
