"""Behavioral checks for final-input image selection and integrity."""
from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import review_release_assets as assets
from PIL import Image


class ReleaseAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "output"

    def image(self, name="figure.png", field="question", placeholder="[图片:figure]", color="black"):
        path = self.source / name
        Image.new("RGB", (12, 10), color).save(path)
        return {
            "path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "role": "stem" if field == "question" else "option",
            "source_placeholder_field": field, "placeholder": placeholder,
            "contains_answer_or_solution": False,
        }

    def question(self, stem="求 [图片:figure] 的值", image_assets=None):
        return {
            "id": "test-question", "question": stem,
            "options": dict(zip("ABCD", ("1", "2", "3", "4"))),
            "image_assets": image_assets or [],
        }

    def export(self, final, canonical, **settings):
        return assets.export_assets(final, canonical, self.output, {"source_root": self.source, **settings})

    def test_preserves_formula_images_and_copies_original_bytes(self):
        image = self.image()
        canonical = self.question(image_assets=[image])
        original = copy.deepcopy(canonical)
        result = self.export(canonical, canonical)
        self.assertEqual(canonical, original)
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0]), {"path", "sha256", "mime_type", "field", "placeholder", "role"})
        self.assertEqual(result[0]["mime_type"], "image/png")
        self.assertEqual((self.output / result[0]["path"]).read_bytes(), (self.source / image["path"]).read_bytes())

    def test_text_rewrite_discards_removed_images_without_reading_them(self):
        image = self.image()
        canonical = self.question(image_assets=[image])
        (self.source / image["path"]).unlink()
        final = self.question("求 2+3 的值")
        final["image_assets"] = [{"path": "old-review-question-screenshot.png", "role": "stem"}]
        self.assertEqual(self.export(final, canonical), [])
        self.assertFalse(self.output.exists())

    def test_same_image_is_bound_to_each_final_field_and_copied_once(self):
        image = self.image()
        canonical = self.question("[图片:figure] 与 [图片:figure]", [image, dict(image)])
        canonical["options"]["A"] = "[图片:figure]"
        canonical["image_assets"].append({**image, "role": "option", "source_placeholder_field": "option_a"})
        assets.assert_source_assets(canonical, self.source)
        final = copy.deepcopy(canonical)
        final["options"]["A"] = "1"
        final["options"]["D"] = "[图片:figure]"
        result = self.export(final, canonical)
        self.assertEqual([a["field"] for a in result], ["question", "option_d"])
        self.assertEqual(result[0]["path"], result[1]["path"])
        self.assertEqual(len(list(self.output.rglob("*.png"))), 1)

    def test_required_geometry_without_placeholder_is_preserved(self):
        image = self.image(placeholder="")
        canonical = self.question("如图，AB=3，求BC", [image])
        final = copy.deepcopy(canonical)
        final["question"] = "如图，AB=3，AC=4，求BC"
        result = self.export(final, canonical)
        self.assertEqual(result[0]["placeholder"], "")
        self.assertEqual(result[0]["role"], "stem")

    def test_unchanged_unplaced_formula_is_not_silently_deleted(self):
        canonical = self.question("求下式的值", [self.image(placeholder="")])
        self.assertEqual(len(self.export(canonical, canonical)), 1)

    def test_explicit_empty_override_drops_obsolete_geometry(self):
        canonical = self.question("如图，求角度", [self.image(placeholder="")])
        final = self.question("已知 A(0,0)、B(3,0)、C(0,4)，求AB")
        self.assertEqual(self.export(final, canonical, assets=[]), [])

    def test_ambiguous_rewrite_of_unplaced_image_requires_explicit_decision(self):
        canonical = self.question("如图，求角度", [self.image(placeholder="")])
        final = self.question("已知 A(0,0)、B(3,0)、C(0,4)，求AB")
        with self.assertRaisesRegex(assets.AssetValidationError, "explicitly replace or remove"):
            self.export(final, canonical)
        self.assertEqual(self.export(final, canonical, drop_unreferenced=True), [])

    def test_explicitly_kept_unplaced_image_survives_rewritten_text(self):
        image = self.image(placeholder="")
        canonical = self.question("如图，求角度", [image])
        final = self.question("求示意图中的角度")
        self.assertEqual(len(self.export(final, canonical, assets=[image])), 1)

    def test_explicit_replacement_uses_new_bytes_and_field(self):
        canonical = self.question("如图，求角度", [self.image(placeholder="")])
        replacement = self.image("new.png", placeholder="", color="red")
        result = self.export(canonical, canonical, assets=[replacement])
        self.assertEqual(result[0]["sha256"], replacement["sha256"])
        self.assertNotEqual(result[0]["sha256"], canonical["image_assets"][0]["sha256"])

    def test_missing_placeholder_source_raises_before_any_output(self):
        canonical = self.question(image_assets=[self.image()])
        final = copy.deepcopy(canonical)
        final["options"]["D"] = "[图片:unknown]"
        with self.assertRaisesRegex(assets.AssetValidationError, "option_d.*unknown"):
            self.export(final, canonical)
        self.assertFalse(self.output.exists())

    def test_malformed_placeholder_is_not_silently_ignored(self):
        canonical = self.question(image_assets=[self.image()])
        final = self.question("求 [图片:figure 的值")
        with self.assertRaisesRegex(assets.AssetValidationError, "malformed image placeholder"):
            self.export(final, canonical)

    def test_hash_mismatch_and_corrupt_image_are_rejected(self):
        image = self.image()
        canonical = self.question(image_assets=[{**image, "sha256": "0" * 64}])
        with self.assertRaisesRegex(assets.AssetValidationError, "SHA-256 mismatch"):
            self.export(canonical, canonical)
        path = self.source / image["path"]
        path.write_bytes(b"not an image")
        image["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        canonical["image_assets"] = [image]
        with self.assertRaisesRegex(assets.AssetValidationError, "cannot be opened"):
            self.export(canonical, canonical)
        self.assertFalse(self.output.exists())

    def test_answer_and_solution_assets_never_satisfy_input_placeholders(self):
        for role in ("answer", "solution"):
            with self.subTest(role=role):
                image = {**self.image(), "role": role}
                canonical = self.question(image_assets=[image])
                with self.assertRaisesRegex(assets.AssetValidationError, "no eligible source image"):
                    self.export(canonical, canonical)
                final = self.question("求2+3")
                self.assertEqual(self.export(final, canonical), [])

    def test_answer_content_flag_blocks_stem_asset(self):
        image = {**self.image(), "contains_answer_or_solution": True}
        canonical = self.question(image_assets=[image])
        with self.assertRaisesRegex(assets.AssetValidationError, "no eligible source image"):
            self.export(canonical, canonical)

    def test_source_validator_checks_original_field_binding(self):
        image = self.image(field="option_a")
        canonical = self.question(image_assets=[image])
        with self.assertRaisesRegex(assets.AssetValidationError, "absent from option_a"):
            assets.assert_source_assets(canonical, self.source)

    def test_conflicting_placeholder_hashes_are_rejected(self):
        first = self.image()
        second = self.image("second.png", field="option_a", color="red")
        canonical = self.question(image_assets=[first, second])
        canonical["options"]["A"] = "[图片:figure]"
        with self.assertRaisesRegex(assets.AssetValidationError, "different image hashes"):
            self.export(canonical, canonical)

    def test_existing_output_with_wrong_bytes_is_not_reused(self):
        canonical = self.question(image_assets=[self.image()])
        result = self.export(canonical, canonical)
        path = self.output / result[0]["path"]
        path.write_bytes(b"modified")
        with self.assertRaisesRegex(assets.AssetValidationError, "conflicts with its content hash"):
            self.export(canonical, canonical)
        self.assertEqual(path.read_bytes(), b"modified")

    def test_flat_four_choice_format_is_supported(self):
        canonical = self.question(image_assets=[self.image()])
        final = {"question": canonical["question"], **{"option_" + k.lower(): v for k, v in canonical["options"].items()}}
        self.assertEqual(self.export(final, canonical)[0]["field"], "question")

    def test_source_path_escape_is_rejected(self):
        image = self.image()
        image["path"] = "../source/../elsewhere.png"
        canonical = self.question(image_assets=[image])
        with self.assertRaisesRegex(assets.AssetValidationError, "outside source_root"):
            self.export(canonical, canonical)


if __name__ == "__main__":
    unittest.main()
