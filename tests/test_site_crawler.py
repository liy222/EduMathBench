"""Regression checks for real collection failures, not a mock of HTTP success."""
import importlib.util
from pathlib import Path
import sys
import unittest
import json
import tempfile

from lxml import html

MODULE = Path(__file__).resolve().parents[1] / "scripts/site_crawler/edumath_crawler.py"
spec = importlib.util.spec_from_file_location("site_crawler", MODULE)
crawler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawler)


class SiteCrawlerTests(unittest.TestCase):
    def record(self, question="-2+3的值是（ ）", options=None, answer="B"):
        r = crawler.base_record("tiku", "1", "https://www.tiku.cn/", {}, "fixture")
        r.update(question=question, options=options or dict(zip("ABCD", ["-5", "1", "-1", "5"])), answer=answer)
        return crawler.validate(r)

    def test_decode_chinese_without_meta(self):
        text = "<div>题干、答案、难度</div>"
        self.assertEqual(crawler.decode_html(text.encode()), text)

    def test_decode_gb18030(self):
        text = "中文数学试题"
        self.assertEqual(crawler.decode_html(text.encode("gb18030"), "text/html; charset=gb18030"), text)

    def test_mathml_fraction_does_not_flatten(self):
        node = html.fromstring('<div><math><mfrac><mi>x</mi><mn>2</mn></mfrac></math></div>')
        self.assertEqual(crawler.readable(node, "https://example.org", "question", []), r"\frac{x}{2}")

    def test_mathjye_html_fraction_is_preserved(self):
        node = html.fromstring('<div><div class="MathJye"><div class="mrow">-<div class="mfrac"><div class="fracZi">4</div><div class="fracLine"></div><div class="fracMu">3</div></div></div></div></div>')
        self.assertEqual(crawler.readable(node, "https://example.org", "question", []), r"-\frac{4}{3}")

    def test_unknown_formula_is_not_silently_flattened(self):
        node = html.fromstring('<div><div class="MathJye"><div class="msqrt">x</div></div></div>')
        result = crawler.readable(node, "https://example.org", "question", [])
        self.assertIn('[公式待转换:', result)
        record = self.record(question=result)
        self.assertEqual(record['status'], 'needs_review')

    def test_superscript_is_preserved(self):
        node = html.fromstring('<div>x<sup>2</sup>+1</div>')
        self.assertEqual(crawler.readable(node, "https://example.org", "question", []), "x^{2}+1")

    def test_text_after_html_comment_is_preserved(self):
        node = html.fromstring('<div><!--B1-->如果两个数的和为负数<!--E1--></div>')
        self.assertEqual(crawler.readable(node, "https://example.org", "question", []), "如果两个数的和为负数")

    def test_hidden_answer_is_not_read(self):
        node = html.fromstring('<div style="display:none">答案A</div>')
        self.assertEqual(crawler.readable(node, "https://example.org", "answer", []), "")

    def test_image_answer_not_misreported_as_text(self):
        r = self.record(answer="[图片:abcdef]")
        r["image_assets"] = [{"role": "answer", "asset_id": "abcdef", "url": "https://example.org/a.png"}]
        r = crawler.validate(r)
        self.assertEqual(r["answer"], "")
        self.assertEqual(r["answer_format"], "image")
        self.assertEqual(r["status"], "needs_review")

    def test_missing_option_does_not_pass(self):
        r = self.record(options=dict(zip("ABCD", ["1", "2", "3", ""])))
        self.assertEqual(r["status"], "needs_review")

    def test_reordered_options_compare_answer_content(self):
        one = self.record(answer="B")
        two = self.record(options=dict(zip("ABCD", ["1", "-5", "5", "-1"])), answer="A")
        two["source_question_id"] = "2"
        two["id"] = "other"
        kept, duplicates = crawler.deduplicate([one, two])
        self.assertEqual(len(kept), 1)
        self.assertTrue(duplicates[0]["answer_content_agrees"])

    def test_different_options_are_not_silently_merged(self):
        one = self.record()
        two = self.record(options=dict(zip("ABCD", ["1", "2", "3", "4"])))
        two["source_question_id"] = "2"
        self.assertEqual(len(crawler.deduplicate([one, two])[0]), 2)

    def test_jyeoo_highlight_is_not_an_explicit_answer(self):
        markup = '''<li class="QUES_LI"><fieldset id="test"><div class="pt1">问题</div>
        <div class="pt2"><table><tr>''' + ''.join(f'<td class="selectoption"><label class="s sh">{x}．{i}</label></td>' for i, x in enumerate('ABCD')) + '''</tr></table></div></fieldset></li>'''
        r = crawler.parse_question("jyeoo", markup, "https://www.jyeoo.com/math/ques/detail/test")
        self.assertEqual(r["answer_format"], "missing")

    def test_transcription_requires_matching_source_image(self):
        r = self.record(answer="")
        r["image_assets"] = [{"role": "answer", "asset_id": "a", "sha256": "real-image-hash"}]
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "review.json"
            file.write_text(json.dumps([{"site": "tiku", "source_question_id": "1", "answer": "A", "image_sha256": "wrong-hash"}]), encoding="utf-8")
            with self.assertRaises(ValueError):
                crawler.apply_transcriptions([r], file)
            self.assertEqual(r["answer"], "")

    def test_transcription_is_separate_from_automatic_answer(self):
        r = self.record(answer="")
        r["image_assets"] = [{"role": "answer", "asset_id": "a", "sha256": "real-image-hash"}]
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "review.json"
            file.write_text(json.dumps([{"site": "tiku", "source_question_id": "1", "answer": "A", "image_sha256": "real-image-hash", "method": "visual_reading"}]), encoding="utf-8")
            crawler.apply_transcriptions([r], file)
            self.assertEqual(r["answer"], "A")
            self.assertEqual(r["source_answer_format"], "image")
            self.assertEqual(r["answer_access"], "source_image_visually_transcribed")
            self.assertTrue(r["answer_transcription"])

    def test_live_site_fixtures(self):
        raw = MODULE.parents[2] / "data/site_trials/20261022/raw"
        if not raw.exists():
            self.skipTest("本地实采样本不存在")
        r = crawler.parse_question("21cnjy", (raw / "21cnjy_detail_2516960.html").read_text(encoding="utf-8"), "https://zujuan.21cnjy.com/question/detail/2516960")
        self.assertEqual(r["options"]["A"], "5或1")
        self.assertEqual(r["answer_format"], "image")
        r = crawler.parse_question("jyeoo", (raw / "jyeoo_detail_0.html").read_text(encoding="utf-8"), "https://www.jyeoo.com/math/ques/detail/test")
        self.assertEqual(r["answer"], "A")
        self.assertIn("如果两个数的和为负数", r["question"])
        self.assertTrue(r["solution"].startswith("【分析】"))
        self.assertEqual(r["solution_format"], "text")
        self.assertNotIn("[图片:", r["question"])

    def test_automatic_export_rejects_transcribed_answer(self):
        r = self.record()
        r["answer_transcription"] = {"method": "visual_reading"}
        with tempfile.TemporaryDirectory() as folder:
            report = crawler.export([r], folder, automatic_only=True)
            self.assertEqual(report["unique_count"], 0)
            self.assertEqual(report["deferred_count"], 1)
            rejected = json.loads((Path(folder) / "deferred.jsonl").read_text(encoding="utf-8"))
            self.assertIn("nonautomatic_answer", rejected["automatic_rejection_reasons"])

    def test_automatic_export_accepts_text_answer_without_solution(self):
        r = self.record()
        with tempfile.TemporaryDirectory() as folder:
            report = crawler.export([r], folder, automatic_only=True)
            self.assertEqual(report["unique_count"], 1)
            self.assertEqual(report["solution_missing_count"], 0)
            self.assertFalse(report["solution_requested"])
            self.assertEqual(report["visually_transcribed_answer_count"], 0)

    def test_answer_image_cannot_enter_automatic_export_as_text(self):
        r = self.record()
        r["source_answer_format"] = "image"
        self.assertIn("source_text_answer_required", crawler.automatic_rejection_reasons(r))

    def test_missing_option_key_cannot_pass(self):
        r = self.record(options={"A": "1", "B": "2", "C": "3"})
        self.assertEqual(r["status"], "needs_review")

    def test_visible_formula_image_url_embeds_mathml(self):
        from urllib.parse import quote
        markup='<math><mfrac><mi>x</mi><mn>2</mn></mfrac></math>'
        node=html.fromstring('<div><img class="mathml" src="/math2svg?mml='+quote(markup)+'"></div>')
        assets=[]
        self.assertEqual(crawler.readable(node,'https://example.org','question',assets),r'$\frac{x}{2}$')
        self.assertEqual(assets,[])

    def test_filename_alt_is_not_formula_text(self):
        node=html.fromstring('<div><img src="/a.png" alt="blob.png"></div>');assets=[]
        text=crawler.readable(node,'https://example.org','question',assets)
        self.assertNotIn('blob.png',text)
        self.assertIn('[图片:',text)

    def test_answer_only_discards_solution_but_keeps_answer_asset(self):
        r = self.record()
        r["solution"] = "一段解析"
        r["image_assets"] = [{"role": "solution", "asset_id": "s"}, {"role": "answer", "asset_id": "a"}]
        result = crawler.answer_only(r)
        self.assertEqual(result["solution"], "")
        self.assertEqual(result["solution_format"], "not_requested")
        self.assertEqual([a["role"] for a in result["image_assets"]], ["answer"])
        self.assertEqual(r["solution"], "一段解析")


if __name__ == "__main__":
    unittest.main()
