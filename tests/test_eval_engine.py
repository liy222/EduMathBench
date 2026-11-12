"""Software validation with generated fixtures, never benchmark test answers."""
import base64
import copy
import builtins
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_engine as engine


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZWkAAAAASUVORK5CYII=")


def item(identifier, **updates):
    row = {
        "id": identifier, "review_no": identifier, "kind": "public", "grade": 7,
        "module": "synthetic-algebra", "difficulty": "synthetic-medium", "parent_id": None,
        "family_id": identifier, "question": "仅作软件检查：选择一个选项。",
        "options": {letter: f"合成选项{letter}" for letter in engine.LABELS},
        "image_assets": [], "split": "dev",
    }
    row.update(updates)
    return row


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="emb-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "synthetic-data"
        (self.root / "inputs").mkdir(parents=True)
        (self.root / "answers").mkdir()
        self.output = Path(self.temporary.name) / "run"

    def dataset(self, rows, answers=None, split="debug"):
        path = self.root / "inputs" / f"{split}_inputs.jsonl"
        engine.atomic_write(path, b"".join(engine.json_bytes(row) + b"\n" for row in rows))
        engine.write_json(self.root / "manifest.json", {
            "version": "synthetic-unit-test", "status": "synthetic",
            "inputs": {split: {"path": f"inputs/{split}_inputs.jsonl", "sha256": engine.file_sha256(path)}},
        })
        if answers is not None:
            engine.atomic_write(self.root / "answers" / f"{split}_answers.jsonl", b"".join(engine.json_bytes({"id": key, "answer": value}) + b"\n" for key, value in answers.items()))
            self.pin_answers(split)
        return path

    def pin_answers(self, split="debug"):
        manifest = engine.read_json(self.root / "manifest.json")
        path = self.root / "answers" / f"{split}_answers.jsonl"
        manifest.setdefault("answers", {})[split] = {"path": f"answers/{split}_answers.jsonl", "sha256": engine.file_sha256(path)}
        engine.write_json(self.root / "manifest.json", manifest)

    def config(self, responses=None, **backend_updates):
        backend = {"type": "mock", "responses": responses or {}, "retry_backoff_seconds": 0, "max_retries": 1}
        backend.update(backend_updates)
        return {"data_root": str(self.root), "split": "debug", "backend": backend}

    def image_item(self, identifier, path="fixture.png", field="question"):
        text = "合成题图[图1]"
        row = item(identifier)
        if field == "question":
            row["question"] = text
        else:
            row["options"][field[-1]] = text
        row["image_assets"] = [{
            "path": path, "sha256": hashlib.sha256(PNG).hexdigest(),
            "mime_type": "image/png", "field": field, "placeholder": "[图1]",
        }]
        return row

    def records(self):
        return engine.read_jsonl(self.output / "predictions.jsonl")


class ParsingTests(unittest.TestCase):
    def test_all_choices_and_format_noise(self):
        examples = {
            "最终答案：A": "A", "**最终答案**：Ｂ。": "B",
            "先排除 A 和 D。\n最终答案：C": "C", "Final answer: (d).": "D",
            "最终答案：\\boxed{B}": "B", "D": "D", "答案：C": "C",
            "最终答案：A\n最终答案：A": "A",
        }
        for response, expected in examples.items():
            with self.subTest(response=response):
                self.assertEqual(engine.parse_answer(response)["answer"], expected)

    def test_multiple_choices_are_never_guessed(self):
        examples = ["最终答案：A 或 B", "最终答案：A/B", "最终答案：A，或者 B", "最终答案：AB",
                    "最终答案：A\n最终答案：D", "最终答案：A。最终答案：B", "答案：A或B",
                    "A、B、C、D", "排除 A，再考虑 B 和 C，故选 D", "最终答案：A-D", "最终答案：A B"]
        for response in examples:
            with self.subTest(response=response):
                result = engine.parse_answer(response)
                self.assertEqual(result["status"], "parse_failure")
                self.assertIsNone(result["answer"])

    def test_explicit_final_has_priority_over_reasoning_and_refusal_words(self):
        self.assertEqual(engine.parse_answer("无法用 A 直接计算。\n最终答案：D")["answer"], "D")
        self.assertEqual(engine.parse_answer("A 是中间变量，B 是干扰项。\n最终答案：C")["answer"], "C")

    def test_refusal_and_empty_are_separate(self):
        self.assertEqual(engine.parse_answer("我无法回答这道题")["status"], "refusal")
        self.assertEqual(engine.parse_answer("I cannot answer.")["status"], "refusal")
        self.assertEqual(engine.parse_answer("最终答案：A", refusal="provider refusal")["status"], "refusal")
        self.assertEqual(engine.parse_answer("")["status"], "parse_failure")


class DatasetTests(FixtureCase):
    def test_manifest_hash_is_checked_before_request(self):
        path = self.dataset([item("x")])
        path.write_text("{}\n", encoding="utf-8")
        with mock.patch.object(engine, "call_mock") as call:
            with self.assertRaisesRegex(engine.EvaluationError, "SHA256 mismatch"):
                engine.execute_run(self.config(), self.output)
            call.assert_not_called()

    def test_manifest_requires_hash(self):
        self.dataset([item("x")])
        engine.write_json(self.root / "manifest.json", {"inputs": {"debug": {"path": "inputs/debug_inputs.jsonl"}}})
        with self.assertRaisesRegex(engine.EvaluationError, "declare a SHA256"):
            engine.load_dataset(self.root, "debug")

    def test_manifest_files_mapping_is_supported(self):
        path = self.dataset([item("x")])
        engine.write_json(self.root / "manifest.json", {"files": {"inputs/debug_inputs.jsonl": {"sha256": engine.file_sha256(path)}}})
        rows, info = engine.load_dataset(self.root, "debug")
        self.assertEqual(rows[0]["id"], "x")
        self.assertEqual(info["dataset_version"], "unknown")

    def test_duplicate_ids_answer_leaks_options_and_split_rejected(self):
        bad_rows = [
            [item("x"), item("x")], [item("x", answer="A")],
            [item("x", options={"A": "1", "B": "2", "C": "3"})],
            [item("x", split="test")], [item("x", kind="variant", parent_id="x")],
        ]
        for rows in bad_rows:
            with self.subTest(rows=rows):
                self.dataset(rows)
                with self.assertRaises(engine.EvaluationError):
                    engine.load_dataset(self.root, "debug")

    def test_asset_paths_and_placeholder_fields_are_checked(self):
        (self.root / "fixture.png").write_bytes(PNG)
        for relative in ("../outside.png", "C:/outside.png", "assets\\fixture.png"):
            with self.subTest(relative=relative):
                _, status, _ = engine.image_content(self.image_item("x", relative), self.root, True)
                self.assertEqual(status, "invalid_image")
        row = self.image_item("x")
        row["image_assets"][0]["placeholder"] = "[不存在]"
        with self.assertRaisesRegex(engine.EvaluationError, "placeholder"):
            engine.validate_item(row, "debug")

    def test_manifest_cannot_redirect_run_to_answers(self):
        self.dataset([item("x")], {"x": "A"})
        answer = self.root / "answers" / "debug_answers.jsonl"
        engine.write_json(self.root / "manifest.json", {"inputs": {"debug": {"path": "answers/debug_answers.jsonl", "sha256": engine.file_sha256(answer)}}})
        with self.assertRaisesRegex(engine.EvaluationError, r"inputs/\*"):
            engine.load_dataset(self.root, "debug")


class RunTests(FixtureCase):
    def test_minimum_image_dimension_pads_only_small_images_and_records_provenance(self):
        from io import BytesIO
        from PIL import Image

        source = Image.new("RGB", (8, 35), (23, 45, 67))
        source_path = self.root / "small.png"
        source.save(source_path, format="PNG")
        row = self.image_item("small", "small.png")
        source_bytes = source_path.read_bytes()
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        row["image_assets"][0]["sha256"] = source_sha
        evidence = []
        blocks, status, error = engine.image_content(row, self.root, True, minimum_dimension=32, processing_evidence=evidence)
        self.assertIsNone(status, error)
        data_url = blocks[-1]["image_url"]["url"]
        derived_bytes = base64.b64decode(data_url.split(",", 1)[1])
        with Image.open(BytesIO(derived_bytes)) as derived:
            self.assertEqual(derived.size, (32, 35))
            self.assertEqual(derived.getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(derived.crop((12, 0, 20, 35)).tobytes(), source.tobytes())
        self.assertEqual(hashlib.sha256(source_path.read_bytes()).hexdigest(), source_sha)
        self.assertEqual(evidence[0]["source_sha256"], source_sha)
        self.assertEqual(evidence[0]["derived_sha256"], hashlib.sha256(derived_bytes).hexdigest())
        self.assertEqual(evidence[0]["source_dimensions"], [8, 35])
        self.assertEqual(evidence[0]["derived_dimensions"], [32, 35])
        self.assertEqual(evidence[0]["operation"], "white_padding")
        self.assertEqual(evidence[0]["padding"], {"left": 12, "top": 0, "right": 12, "bottom": 0})
        self.assertTrue(evidence[0]["pillow_version"])

    def test_minimum_image_dimension_keeps_large_bytes_and_rejects_bad_inputs(self):
        from io import BytesIO
        from PIL import Image

        large_path = self.root / "large.png"
        Image.new("RGB", (40, 35), (1, 2, 3)).save(large_path, format="PNG")
        large = self.image_item("large", "large.png")
        original = large_path.read_bytes()
        large["image_assets"][0]["sha256"] = hashlib.sha256(original).hexdigest()
        evidence = []
        blocks, status, error = engine.image_content(large, self.root, True, minimum_dimension=32, processing_evidence=evidence)
        self.assertIsNone(status, error)
        self.assertEqual(base64.b64decode(blocks[-1]["image_url"]["url"].split(",", 1)[1]), original)
        self.assertEqual(evidence[0]["operation"], "none")

        gif_path = self.root / "animated.gif"
        frames = [Image.new("RGB", (8, 8), color) for color in ((255, 0, 0), (0, 0, 255))]
        frames[0].save(gif_path, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
        animated = self.image_item("animated", "animated.gif")
        animated_bytes = gif_path.read_bytes()
        animated["image_assets"][0].update(sha256=hashlib.sha256(animated_bytes).hexdigest(), mime_type="image/gif")
        _, status, error = engine.image_content(animated, self.root, True, minimum_dimension=32)
        self.assertEqual(status, "invalid_image")
        self.assertIn("Multi-frame", error)

        broken_path = self.root / "broken.png"
        broken_path.write_bytes(b"\x89PNG\r\n\x1a\nnot-an-image")
        broken = self.image_item("broken", "broken.png")
        broken["image_assets"][0]["sha256"] = hashlib.sha256(broken_path.read_bytes()).hexdigest()
        _, status, error = engine.image_content(broken, self.root, True, minimum_dimension=32)
        self.assertEqual(status, "invalid_image")
        self.assertIn("Cannot process image", error)

    def test_minimum_image_dimension_is_opt_in_and_pillow_is_required_only_when_enabled(self):
        (self.root / "fixture.png").write_bytes(PNG)
        row = self.image_item("default")
        with mock.patch.object(builtins, "__import__", side_effect=lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError()) if name == "PIL" else original_import(name, *args, **kwargs)):
            original_import = builtins.__import__
            blocks, status, error = engine.image_content(row, self.root, True)
            self.assertIsNone(status, error)
            self.assertEqual(base64.b64decode(blocks[-1]["image_url"]["url"].split(",", 1)[1]), PNG)
            _, status, error = engine.image_content(row, self.root, True, minimum_dimension=32)
            self.assertEqual(status, "invalid_image")
            self.assertIn("Pillow is required", error)

    def test_minimum_image_dimension_configuration_validation(self):
        for value in (-1, 1025, True, 1.5, "32"):
            config = self.config(minimum_image_dimension=value)
            with self.subTest(value=value), self.assertRaisesRegex(engine.EvaluationError, "minimum_image_dimension"):
                engine.normalize_config(config)

    def test_run_records_image_processing_evidence_in_item_detail(self):
        from PIL import Image

        image_path = self.root / "small.png"
        Image.new("RGB", (8, 35), (23, 45, 67)).save(image_path, format="PNG")
        row = self.image_item("small", "small.png")
        row["image_assets"][0]["sha256"] = hashlib.sha256(image_path.read_bytes()).hexdigest()
        self.dataset([row])
        config = self.config(supports_images=True, minimum_image_dimension=32)
        result = engine.execute_run(config, self.output)
        detail = engine.read_json(self.output / "items" / engine.item_filename("small"))
        self.assertEqual(result["status_counts"], {"ok": 1})
        self.assertEqual(detail["image_processing"][0]["operation"], "white_padding")
        request_image = detail["raw_request"]["messages"][1]["content"][-1]["image_url"]["url"]
        self.assertTrue(request_image.startswith("data:image/png;base64,"))

    def test_priority_ids_reorders_without_dropping_rows_and_preserves_default_order(self):
        rows = [item("a"), item("b"), item("c"), item("d")]
        self.dataset(rows)
        config = engine.normalize_config(self.config())
        self.assertEqual([row["id"] for row in engine.prioritize_items(rows, config)], ["a", "b", "c", "d"])
        config["priority_ids"] = ["c", "a"]
        ordered = engine.prioritize_items(rows, config)
        self.assertEqual([row["id"] for row in ordered], ["c", "a", "b", "d"])
        self.assertEqual({row["id"] for row in ordered}, {row["id"] for row in rows})
        self.assertEqual(len(ordered), len(rows))

    def test_priority_configuration_and_missing_ids_fail_before_any_request(self):
        for bad in (["x", "x"], [""], ["x", 1], "x", None):
            config = self.config()
            config["priority_ids"] = bad
            with self.subTest(priority_ids=bad), self.assertRaisesRegex(engine.EvaluationError, "priority_ids"):
                engine.normalize_config(config)
        self.dataset([item("a"), item("b")])
        config = self.config(type="openai-compatible", model="test-model", base_url="https://example.invalid/v1")
        config["priority_ids"] = ["missing"]
        with mock.patch.object(engine, "call_openai", side_effect=AssertionError("request must not occur")) as call:
            with self.assertRaisesRegex(engine.EvaluationError, "unknown dataset ids"):
                engine.execute_run(config, self.output)
            call.assert_not_called()

    def test_provider_output_parameter_and_optional_temperature(self):
        row = item("x")
        original = engine.build_request(row, engine.normalize_config(self.config())["backend"], [])
        self.assertEqual(original["temperature"], 0)
        self.assertEqual(original["max_tokens"], 512)
        self.assertNotIn("max_completion_tokens", original)

        for token_parameter in ("max_tokens", "max_completion_tokens"):
            with self.subTest(token_parameter=token_parameter):
                backend = engine.normalize_config(self.config(
                    temperature=None, output_token_parameter=token_parameter,
                    max_output_tokens=17,
                ))["backend"]
                request = engine.build_request(row, backend, [])
                self.assertNotIn("temperature", request)
                self.assertEqual(request[token_parameter], 17)
                other_parameter = "max_tokens" if token_parameter == "max_completion_tokens" else "max_completion_tokens"
                self.assertNotIn(other_parameter, request)

        for bad_parameter in ("max_output_tokens", "temperature", None, [], 7):
            with self.subTest(bad_parameter=bad_parameter), self.assertRaisesRegex(engine.EvaluationError, "output_token_parameter"):
                engine.normalize_config(self.config(output_token_parameter=bad_parameter))
        for extra in ({"max_tokens": 2}, {"max_completion_tokens": 2}, {"temperature": 0.1}):
            with self.subTest(extra=extra), self.assertRaisesRegex(engine.EvaluationError, "protected"):
                engine.normalize_config(self.config(request_extra=extra))
        for bad_temperature in (True, "0", -0.01, 2.01):
            with self.subTest(bad_temperature=bad_temperature), self.assertRaisesRegex(engine.EvaluationError, "temperature"):
                engine.normalize_config(self.config(temperature=bad_temperature))

    def test_request_extras_support_non_thinking_controls_and_protect_core_fields(self):
        for extra in ({"enable_thinking": False}, {"thinking": {"type": "disabled"}}):
            with self.subTest(extra=extra):
                backend = engine.normalize_config(self.config(request_extra=extra))["backend"]
                request = engine.build_request(item("x"), backend, [])
                self.assertEqual({key: request[key] for key in extra}, extra)
                self.assertEqual(request["model"], backend["model"])
                self.assertEqual(request["messages"][0]["content"], engine.SYSTEM_PROMPT)
        for name in ("model", "messages", "stream", "headers", "Authorization", "api_key", "access_token", "api_key_env"):
            with self.subTest(name=name), self.assertRaisesRegex(engine.EvaluationError, "protected"):
                engine.normalize_config(self.config(request_extra={name: "not-allowed"}))

    def test_budget_and_interval_configuration_validation(self):
        for name, value in (("max_requests", -1), ("max_requests", True), ("max_total_tokens", 1.5)):
            config = self.config()
            config[name] = value
            with self.subTest(name=name, value=value), self.assertRaises(engine.EvaluationError):
                engine.normalize_config(config)
        for value in (-0.01, 60.01, True, "1"):
            with self.subTest(interval=value), self.assertRaisesRegex(engine.EvaluationError, "request_interval_seconds"):
                engine.normalize_config(self.config(request_interval_seconds=value))

    def test_mock_never_sleeps_for_interval_or_consumes_remote_budgets(self):
        self.dataset([item("a"), item("b")])
        config = self.config(request_interval_seconds=60)
        config.update(max_requests=0, max_total_tokens=0)
        with mock.patch.object(engine.time, "sleep", side_effect=AssertionError("mock rate wait")):
            result = engine.execute_run(config, self.output)
        self.assertEqual(result["status_counts"], {"ok": 2})
        self.assertEqual(result["budget_usage"]["remote_request_count"], 0)

    def test_run_is_answer_blind_and_score_requires_answers(self):
        self.dataset([item("x")])
        seen = []
        original = engine.read_jsonl

        def audited_read(path):
            seen.append(str(path))
            self.assertNotIn("answers", Path(path).parts)
            return original(path)

        with mock.patch.object(engine, "read_jsonl", side_effect=audited_read):
            result = engine.execute_run(self.config({"x": "最终答案：B"}), self.output)
        self.assertTrue(result["synthetic"])
        self.assertEqual(self.records()[0]["answer"], "B")
        with self.assertRaisesRegex(engine.EvaluationError, "declare a SHA256"):
            engine.score_run(self.output)

    def test_resume_has_zero_duplicate_requests_and_keeps_run_id(self):
        self.dataset([item("a"), item("b")])
        config = self.config({"a": "A", "b": "B"})
        first = engine.execute_run(config, self.output)
        before = (self.output / "predictions.jsonl").read_bytes()
        with mock.patch.object(engine, "call_mock", side_effect=AssertionError("duplicate request")):
            resumed = engine.execute_run(config, self.output, resume=True)
        self.assertEqual(resumed["newly_processed"], 0)
        self.assertEqual(resumed["run_id"], first["run_id"])
        self.assertEqual((self.output / "predictions.jsonl").read_bytes(), before)
        with self.assertRaisesRegex(engine.EvaluationError, "already exists"):
            engine.execute_run(config, self.output)

    def test_resume_binds_configuration_prompt_manifest_and_input(self):
        self.dataset([item("x")])
        config = self.config()
        engine.execute_run(config, self.output)
        changed = copy.deepcopy(config)
        changed["backend"]["temperature"] = 0.2
        with self.assertRaisesRegex(engine.EvaluationError, "hash changed"):
            engine.execute_run(changed, self.output, resume=True)
        with mock.patch.object(engine, "SYSTEM_PROMPT", "different prompt"):
            with self.assertRaisesRegex(engine.EvaluationError, "hash changed"):
                engine.execute_run(config, self.output, resume=True)
        manifest = engine.read_json(self.root / "manifest.json")
        manifest["status"] = "changed"
        engine.write_json(self.root / "manifest.json", manifest)
        with self.assertRaisesRegex(engine.EvaluationError, "hash changed"):
            engine.execute_run(config, self.output, resume=True)

    def test_recover_complete_item_without_repeating_request(self):
        self.dataset([item("x")])
        config = self.config()
        engine.execute_run(config, self.output)
        (self.output / "predictions.jsonl").unlink()
        with mock.patch.object(engine, "call_mock", side_effect=AssertionError("duplicate request")):
            result = engine.execute_run(config, self.output, resume=True)
        self.assertEqual(result["recovered_commits"], 1)
        self.assertEqual(len(self.records()), 1)

    def test_recover_saved_unfinalized_response_without_request(self):
        self.dataset([item("x")])
        config = self.config({"x": "B"})
        engine.execute_run(config, self.output)
        (self.output / "predictions.jsonl").unlink()
        path = self.output / "items" / engine.item_filename("x")
        detail = engine.read_json(path)
        detail["complete"] = False
        engine.write_json(path, detail)
        with mock.patch.object(engine, "call_mock", side_effect=AssertionError("duplicate request")):
            engine.execute_run(config, self.output, resume=True)
        self.assertEqual(self.records()[0]["answer"], "B")

    def test_timeout_refusal_parse_failure_and_retry_counts(self):
        self.dataset([item("retry"), item("timeout"), item("refusal"), item("ambiguous")])
        config = self.config({
            "retry": [{"error": "api_error", "retryable": True}, "最终答案：D"],
            "timeout": {"error": "timeout", "retryable": True},
            "refusal": {"refusal": "Synthetic refusal"}, "ambiguous": "最终答案：A/B",
        })
        engine.execute_run(config, self.output)
        records = {row["id"]: row for row in self.records()}
        self.assertEqual(records["retry"]["answer"], "D")
        self.assertEqual(records["retry"]["attempt_count"], 2)
        self.assertEqual(records["timeout"]["status"], "timeout")
        self.assertEqual(records["timeout"]["attempt_count"], 2)
        self.assertEqual(records["refusal"]["status"], "refusal")
        self.assertEqual(records["ambiguous"]["status"], "parse_failure")

    def test_missing_corrupt_and_unsupported_images_are_distinct(self):
        (self.root / "fixture.png").write_bytes(PNG)
        missing = self.image_item("missing", "missing.png")
        corrupt = self.image_item("corrupt")
        corrupt["image_assets"][0]["sha256"] = "0" * 64
        unsupported = self.image_item("unsupported")
        self.dataset([missing, corrupt, unsupported])
        with mock.patch.object(engine, "call_mock", side_effect=AssertionError("image skip requested")):
            engine.execute_run(self.config(), self.output)
        self.assertEqual({row["id"]: row["status"] for row in self.records()}, {"missing": "missing_image", "corrupt": "invalid_image", "unsupported": "unsupported_image"})
        self.assertFalse(any(row["attempted"] for row in self.records()))

    def test_only_declared_images_are_attached_to_their_fields(self):
        (self.root / "fixture.png").write_bytes(PNG)
        (self.root / "unrelated.png").write_bytes(b"SECRET-UNRELATED")
        self.dataset([self.image_item("x", field="options.B")])
        engine.execute_run(self.config(supports_images=True), self.output)
        detail = engine.read_json(self.output / "items" / engine.item_filename("x"))
        content = detail["raw_request"]["messages"][1]["content"]
        self.assertEqual(sum(block["type"] == "image_url" for block in content), 1)
        self.assertIn("options.B", content[1]["text"])
        self.assertEqual(content[2]["image_url"]["url"], "data:image/png;base64," + base64.b64encode(PNG).decode())

    def test_test_all_execution_requires_explicit_flag_before_loading_data(self):
        for split in ("test", "all"):
            config = self.config()
            config["split"] = split
            with self.subTest(split=split), mock.patch.object(engine, "load_dataset") as load:
                with self.assertRaisesRegex(engine.EvaluationError, "requires --allow-test"):
                    engine.execute_run(config, self.output)
                load.assert_not_called()

    def test_run_lock_and_truncated_journal_fail_safely(self):
        self.dataset([item("x")])
        self.output.mkdir()
        (self.output / ".run.lock").write_text("synthetic concurrent process")
        with self.assertRaisesRegex(engine.EvaluationError, "locked"):
            engine.execute_run(self.config(), self.output)
        (self.output / ".run.lock").unlink()
        journal = self.output / "probe.jsonl"
        journal.write_bytes(b'{"partial":')
        with self.assertRaisesRegex(engine.EvaluationError, "Incomplete journal"):
            engine.append_jsonl_atomic(journal, {"id": "new"})
        self.assertEqual(journal.read_bytes(), b'{"partial":')


class ScoreTests(FixtureCase):
    def test_answer_manifest_hash_detects_replacement_without_manifest_change(self):
        self.dataset([item("x")], {"x": "A"})
        engine.execute_run(self.config(), self.output)
        path = self.root / "answers" / "debug_answers.jsonl"
        engine.atomic_write(path, engine.json_bytes({"id": "x", "answer": "B"}) + b"\n")
        with self.assertRaisesRegex(engine.EvaluationError, "Answer SHA256 mismatch"):
            engine.score_run(self.output)

    def test_answer_mapping_can_use_a_pinned_custom_path(self):
        self.dataset([item("x")], {"x": "A"})
        old = self.root / "answers" / "debug_answers.jsonl"
        custom = self.root / "answers" / "custom_debug_answers.jsonl"
        old.rename(custom)
        manifest = engine.read_json(self.root / "manifest.json")
        manifest["answers"]["debug"]["path"] = "answers/custom_debug_answers.jsonl"
        engine.write_json(self.root / "manifest.json", manifest)
        engine.execute_run(self.config(), self.output)
        report = engine.score_run(self.output)
        self.assertTrue(report["answer_tables"][0]["manifest_verified"])
        self.assertEqual(report["overall"]["correct"], 1)

    def test_coverage_failures_and_group_accuracy_denominators(self):
        (self.root / "fixture.png").write_bytes(PNG)
        rows = [item("good"), item("wrong", grade=8), item("timeout"), item("invalid"), self.image_item("image"), item("unrun")]
        self.dataset(rows, {row["id"]: "A" for row in rows})
        config = self.config({"good": "A", "wrong": "B", "timeout": {"error": "timeout"}, "invalid": "A/B"})
        engine.execute_run(config, self.output)
        engine.atomic_write(self.output / "predictions.jsonl", b"".join(engine.json_bytes(row) + b"\n" for row in self.records() if row["id"] != "unrun"))
        report = engine.score_run(self.output)
        overall = report["overall"]
        self.assertEqual((overall["total"], overall["attempted"], overall["parsed"], overall["correct"], overall["unrun"], overall["skipped"]), (6, 4, 2, 1, 1, 1))
        self.assertEqual(overall["accuracy"], 1 / 4)
        self.assertEqual(overall["accuracy_among_parsed"], 1 / 2)
        self.assertEqual(overall["request_coverage"], 4 / 6)
        self.assertEqual(overall["answer_coverage"], 2 / 6)
        self.assertEqual(report["groups"]["grade"]["8"]["accuracy"], 0)
        self.assertTrue(report["synthetic"])

    def test_score_refuses_missing_duplicate_and_invalid_answers(self):
        self.dataset([item("x")], {"wrong-id": "A"})
        engine.execute_run(self.config(), self.output)
        with self.assertRaisesRegex(engine.EvaluationError, "missing"):
            engine.score_run(self.output)
        path = self.root / "answers" / "debug_answers.jsonl"
        for rows, reason in [([{"id": "x", "answer": "A"}] * 2, "Duplicate"), ([{"id": "x", "answer": "A/B"}], "Invalid")]:
            with self.subTest(reason=reason):
                engine.atomic_write(path, b"".join(engine.json_bytes(row) + b"\n" for row in rows))
                # Keep the manifest stable for score's dataset identity check:
                # load_answers alone validates row syntax after the new hash.
                self.pin_answers()
                with self.assertRaisesRegex(engine.EvaluationError, reason):
                    engine.load_answers(self.root, "debug", {"x"})

    def test_tampered_journal_or_config_is_rejected(self):
        self.dataset([item("x")], {"x": "A"})
        engine.execute_run(self.config(), self.output)
        records = self.records()
        records[0]["answer"] = "B"
        engine.atomic_write(self.output / "predictions.jsonl", engine.json_bytes(records[0]) + b"\n")
        with self.assertRaisesRegex(engine.EvaluationError, "mismatch"):
            engine.score_run(self.output)
        metadata = engine.read_json(self.output / "run.json")
        metadata["config"]["backend"]["temperature"] = 0.5
        engine.write_json(self.output / "run.json", metadata)
        with self.assertRaisesRegex(engine.EvaluationError, "configuration or prompt"):
            engine.score_run(self.output)

    def test_parent_variant_joint_and_conditional_use_actual_pairs_only(self):
        rows = [item("p1", family_id="f1"), item("v1", kind="variant", parent_id="p1", family_id="f1"),
                item("p2", family_id="f2"), item("v2", kind="variant", parent_id="p2", family_id="f2"),
                item("p3", family_id="f3"), item("v3", kind="variant", parent_id="p3", family_id="f3"),
                item("orphan", kind="variant", parent_id="absent")]
        self.dataset(rows, {row["id"]: "A" for row in rows})
        engine.execute_run(self.config({"p1": "A", "v1": "A", "p2": "A", "v2": "A/B", "p3": "B", "v3": "A"}), self.output)
        report = engine.score_run(self.output)
        pairs = report["pairs"]
        self.assertEqual(pairs["actual_complete_pairs"], 3)
        self.assertEqual(pairs["joint_accuracy"], 1 / 3)
        self.assertEqual(pairs["conditional_variant_accuracy_given_parent_correct"], 1 / 2)
        self.assertEqual(pairs["excluded"]["missing_parent"], 1)

    def test_pair_metrics_reject_cross_split_and_skipped_pairs(self):
        rows = [item("p"), item("cross", split="test", kind="variant", parent_id="p"),
                item("skip", kind="variant", parent_id="p", family_id="p")]
        predictions = {"p": {"attempted": True, "status": "ok", "answer": "A"}, "cross": {"attempted": True, "status": "ok", "answer": "A"}, "skip": {"attempted": False, "status": "unsupported_image", "answer": None}}
        pairs = engine.pair_metrics(rows, predictions, {row["id"]: "A" for row in rows})
        self.assertEqual(pairs["actual_complete_pairs"], 0)
        self.assertEqual(pairs["excluded"]["cross_split"], 1)
        self.assertEqual(pairs["excluded"]["not_both_attempted"], 1)
        self.assertIsNone(pairs["joint_accuracy"])
        self.assertIsNone(pairs["conditional_variant_accuracy_given_parent_correct"])


class HttpBackendTests(FixtureCase):
    def start_server(self, replies):
        received = []
        state = {"replies": list(replies)}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(handler):
                body = handler.rfile.read(int(handler.headers["Content-Length"]))
                received.append({"path": handler.path, "authorization": handler.headers.get("Authorization"), "request": json.loads(body)})
                status, response = state["replies"].pop(0)
                handler.send_response(status)
                handler.send_header("Content-Type", "application/json")
                if status == 302:
                    handler.send_header("Location", "/redirect-target")
                handler.end_headers()
                payload = response.encode() if isinstance(response, str) else engine.json_bytes(response)
                handler.wfile.write(payload)

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.addCleanup(stop)
        return f"http://127.0.0.1:{server.server_port}/v1", received

    def real_config(self, url, **updates):
        config = self.config(type="openai-compatible", model="local-protocol-fixture", base_url=url, api_key_env="EMB_UNIT_TEST_API_KEY")
        config["backend"].update(updates)
        return config

    def test_request_budget_counts_retries_and_resume_cannot_reset_it(self):
        self.dataset([item("first"), item("second")], {"first": "A", "second": "A"})
        url, received = self.start_server([(429, {"error": "retry"}), (200, {"choices": [{"message": {"content": "A"}}], "usage": {"total_tokens": 4}})])
        config = self.real_config(url)
        config["max_requests"] = 2
        with mock.patch.dict(os.environ, {"EMB_UNIT_TEST_API_KEY": "synthetic-key"}):
            first = engine.execute_run(config, self.output)
            with mock.patch.object(engine, "call_openai", side_effect=AssertionError("budget bypass")):
                resumed = engine.execute_run(config, self.output, resume=True)
            changed = copy.deepcopy(config)
            changed["max_requests"] = 3
            with self.assertRaisesRegex(engine.EvaluationError, "hash changed"):
                engine.execute_run(changed, self.output, resume=True)
        self.assertEqual(len(received), 2)
        self.assertEqual(first["budget_usage"]["remote_request_count"], 2)
        self.assertEqual(resumed["budget_usage"]["remote_request_count"], 2)
        self.assertEqual(self.records()[1]["status"], "unrun_budget_limit")
        overall = engine.score_run(self.output)["overall"]
        self.assertEqual((overall["attempted"], overall["unrun"], overall["unrun_budget_limit"]), (1, 1, 1))
        self.assertEqual(overall["accuracy"], 1)
        self.assertEqual(overall["request_coverage"], 0.5)

    def test_zero_request_budget_never_calls_provider(self):
        self.dataset([item("x")], {"x": "A"})
        config = self.real_config("http://127.0.0.1:9/v1")
        config["max_requests"] = 0
        with mock.patch.dict(os.environ, {"EMB_UNIT_TEST_API_KEY": "synthetic-key"}), mock.patch.object(engine, "call_openai", side_effect=AssertionError("zero budget requested")):
            result = engine.execute_run(config, self.output)
        self.assertEqual(result["status_counts"], {"unrun_budget_limit": 1})
        self.assertIsNone(engine.score_run(self.output)["overall"]["accuracy"])

    def test_request_is_reserved_before_call_and_interruption_cannot_bypass_limit(self):
        self.dataset([item("x")])
        config = self.real_config("http://127.0.0.1:9/v1")
        config["max_requests"] = 1
        with mock.patch.dict(os.environ, {"EMB_UNIT_TEST_API_KEY": "synthetic-key"}):
            with mock.patch.object(engine, "call_openai", side_effect=KeyboardInterrupt("simulated interrupted call")):
                with self.assertRaises(KeyboardInterrupt):
                    engine.execute_run(config, self.output)
            with mock.patch.object(engine, "call_openai", side_effect=AssertionError("interruption reset allowance")):
                result = engine.execute_run(config, self.output, resume=True)
        self.assertEqual(result["budget_usage"]["remote_request_count"], 1)
        self.assertEqual(result["budget_usage"]["unknown_usage_request_count"], 1)
        self.assertEqual(result["budget_usage"]["interrupted_or_inflight_request_count"], 1)

    def test_observed_token_threshold_stops_future_calls_and_reports_overshoot(self):
        self.dataset([item("first"), item("second")], {"first": "A", "second": "A"})
        url, received = self.start_server([(200, {"choices": [{"message": {"content": "A"}}], "usage": {"total_tokens": 7}})])
        config = self.real_config(url)
        config["max_total_tokens"] = 5
        with mock.patch.dict(os.environ, {"EMB_UNIT_TEST_API_KEY": "synthetic-key"}):
            result = engine.execute_run(config, self.output)
        self.assertEqual(len(received), 1)
        self.assertEqual(result["budget_usage"]["observed_total_tokens"], 7)
        self.assertEqual(self.records()[1]["budget_limit_reason"], "max_total_tokens_observed")
        self.assertEqual(engine.score_run(self.output)["overall"]["accuracy"], 1)

    def test_unknown_usage_is_explicit_and_not_assumed_zero_for_completeness(self):
        self.dataset([item("unknown"), item("known"), item("unrun")])
        response = {"choices": [{"message": {"content": "A"}}]}
        known = {**response, "usage": {"prompt_tokens": 2, "completion_tokens": 3}}
        url, received = self.start_server([(200, response), (200, known)])
        config = self.real_config(url)
        config["max_total_tokens"] = 5
        with mock.patch.dict(os.environ, {"EMB_UNIT_TEST_API_KEY": "synthetic-key"}):
            result = engine.execute_run(config, self.output)
        self.assertEqual(len(received), 2)
        usage = result["budget_usage"]
        self.assertEqual(usage["observed_total_tokens"], 5)
        self.assertEqual(usage["unknown_usage_request_count"], 1)
        self.assertFalse(usage["token_usage_complete"])
        self.assertIn("not_a_hard", usage["token_limit_kind"])

    def test_usage_commit_interruption_is_recovered_without_double_counting(self):
        self.dataset([item("x"), item("unrun")])
        url, received = self.start_server([(200, {"choices": [{"message": {"content": "A"}}], "usage": {"total_tokens": 3}})])
        config = self.real_config(url)
        config["max_total_tokens"] = 3
        original_write = engine.write_json

        def interrupt_budget_commit(path, value):
            if Path(path).name == "run.json" and value.get("remote_attempts") and value["remote_attempts"][-1]["state"] == "completed":
                raise OSError("synthetic crash between item and usage commits")
            return original_write(path, value)

        with mock.patch.dict(os.environ, {"EMB_UNIT_TEST_API_KEY": "synthetic-key"}):
            with mock.patch.object(engine, "write_json", side_effect=interrupt_budget_commit):
                with self.assertRaises(OSError):
                    engine.execute_run(config, self.output)
            with mock.patch.object(engine, "call_openai", side_effect=AssertionError("saved response was repeated")):
                result = engine.execute_run(config, self.output, resume=True)
        self.assertEqual(len(received), 1)
        self.assertEqual(result["budget_usage"]["observed_total_tokens"], 3)
        self.assertEqual(result["budget_usage"]["remote_request_count"], 1)
        self.assertEqual(self.records()[0]["answer"], "A")
        self.assertEqual(self.records()[1]["status"], "unrun_budget_limit")

    def test_remote_interval_waits_are_bounded_and_request_extras_reach_provider(self):
        self.dataset([item("a"), item("b")])
        response = {"choices": [{"message": {"content": "A"}}]}
        url, received = self.start_server([(200, response), (200, response)])
        config = self.real_config(url, request_interval_seconds=60, request_extra={"enable_thinking": False})
        with mock.patch.dict(os.environ, {"EMB_UNIT_TEST_API_KEY": "synthetic-key"}), mock.patch.object(engine.time, "sleep") as sleep:
            engine.execute_run(config, self.output)
        self.assertEqual(sleep.call_count, 1)
        self.assertGreater(sleep.call_args.args[0], 0)
        self.assertLessEqual(sleep.call_args.args[0], 60)
        self.assertIs(received[0]["request"]["enable_thinking"], False)

    def test_real_http_protocol_retries_multimodal_usage_and_secret_redaction(self):
        (self.root / "fixture.png").write_bytes(PNG)
        self.dataset([self.image_item("x")], {"x": "C"})
        secret = "synthetic-unit-key-never-store"
        response = {"choices": [{"message": {"content": f"{secret}\n最终答案：C"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}
        url, received = self.start_server([(429, {"error": secret}), (200, response)])
        with mock.patch.dict(os.environ, {"EMB_UNIT_TEST_API_KEY": secret}):
            engine.execute_run(self.real_config(url, supports_images=True), self.output)
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0]["path"], "/v1/chat/completions")
        self.assertEqual(received[0]["authorization"], f"Bearer {secret}")
        self.assertEqual(received[0]["request"]["messages"][0]["content"], engine.SYSTEM_PROMPT)
        image_blocks = received[0]["request"]["messages"][1]["content"]
        self.assertTrue(image_blocks[-1]["image_url"]["url"].startswith("data:image/png;base64,"))
        record = self.records()[0]
        self.assertFalse(record["synthetic"])
        self.assertEqual(record["answer"], "C")
        self.assertEqual(record["attempt_count"], 2)
        self.assertEqual(record["usage"]["total_tokens"], 13)
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret.encode(), path.read_bytes(), str(path))

    def test_http_non_json_multiple_choices_and_nonretryable_error(self):
        self.dataset([item("nonjson"), item("multiple"), item("error")])
        url, received = self.start_server([(200, "not JSON"), (200, {"choices": [{"message": {"content": "A"}}, {"message": {"content": "B"}}]}), (401, {"error": "not authorized"})])
        with mock.patch.dict(os.environ, {"EMB_UNIT_TEST_API_KEY": "synthetic-key"}):
            engine.execute_run(self.real_config(url), self.output)
        self.assertEqual([row["status"] for row in self.records()], ["invalid_response", "invalid_response", "api_error"])
        self.assertEqual(len(received), 3)

    def test_redirect_is_not_followed_with_credentials(self):
        self.dataset([item("x")])
        url, received = self.start_server([(302, {"error": "redirect"})])
        with mock.patch.dict(os.environ, {"EMB_UNIT_TEST_API_KEY": "synthetic-key"}):
            engine.execute_run(self.real_config(url), self.output)
        self.assertEqual(len(received), 1)
        self.assertEqual(self.records()[0]["status"], "api_error")

    def test_missing_env_or_inline_keys_fail_before_request(self):
        self.dataset([item("x")])
        config = self.real_config("http://127.0.0.1:9/v1")
        with mock.patch.dict(os.environ, {"EMB_UNIT_TEST_API_KEY": ""}), mock.patch.object(engine, "call_openai") as call:
            with self.assertRaisesRegex(engine.EvaluationError, "empty"):
                engine.execute_run(config, self.output)
            call.assert_not_called()
        config["backend"]["api_key"] = "must-be-rejected"
        with self.assertRaisesRegex(engine.EvaluationError, "credentials only"):
            engine.normalize_config(config)


class AtomicWriteTests(FixtureCase):
    def test_uncommitted_reservation_stays_charged_and_becomes_unknown_on_resume(self):
        metadata = {"run_id": "synthetic-run", "remote_attempts": [{
            "reservation_id": "synthetic-interruption", "item_id": "synthetic-pending",
            "attempt": 1, "started_at": "2026-01-01T00:00:00+00:00",
            "state": "reserved", "total_tokens": None,
        }]}
        engine.reconcile_remote_attempts(metadata, self.output, [item("synthetic-pending")])
        self.assertEqual(metadata["remote_attempts"][0]["state"], "interrupted_unknown")
        self.assertEqual(metadata["budget_usage"]["remote_request_count"], 1)
        self.assertEqual(metadata["budget_usage"]["unknown_usage_request_count"], 1)
        self.assertEqual(metadata["budget_usage"]["interrupted_or_inflight_request_count"], 1)

    def test_transient_destination_lock_retries_without_truncating(self):
        path = self.root / "ledger.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old-committed-version")
        replace = engine.os.replace
        calls = []
        def briefly_locked(source, destination):
            calls.append((source, destination))
            if len(calls) < 3:
                self.assertEqual(path.read_bytes(), b"old-committed-version")
                raise PermissionError("synthetic sharing violation")
            return replace(source, destination)
        with mock.patch.object(engine.os, "replace", side_effect=briefly_locked), mock.patch.object(engine.time, "sleep") as pause:
            engine.atomic_write(path, b"new-complete-version")
        self.assertEqual(path.read_bytes(), b"new-complete-version")
        self.assertEqual(len(calls), 3)
        self.assertEqual(pause.call_count, 2)

    def test_permanent_destination_lock_is_bounded_and_keeps_old_bytes(self):
        path = self.root / "ledger.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old-committed-version")
        with mock.patch.object(engine.os, "replace", side_effect=PermissionError("synthetic permanent lock")) as replace, mock.patch.object(engine.time, "sleep") as pause:
            with self.assertRaises(PermissionError):
                engine.atomic_write(path, b"must-not-partially-commit")
        self.assertEqual(replace.call_count, 12)
        self.assertEqual(pause.call_count, 11)
        self.assertEqual(path.read_bytes(), b"old-committed-version")

    def test_resume_records_new_implementation_without_repeating_items(self):
        self.dataset([item("synthetic-resume")])
        config = self.config({"synthetic-resume": "最终答案：B"})
        engine.execute_run(config, self.output)
        metadata = engine.read_json(self.output / "run.json")
        metadata["engine_sha256"] = "0" * 64
        engine.write_json(self.output / "run.json", metadata)
        with mock.patch.object(engine, "call_mock", side_effect=AssertionError("committed item must not be repeated")):
            engine.execute_run(config, self.output, resume=True)
        resumed = engine.read_json(self.output / "run.json")
        self.assertEqual(resumed["engine_sha256"], "0" * 64)
        self.assertEqual(resumed["resume_implementations"][0]["engine_sha256"], engine.file_sha256(Path(engine.__file__)))
        self.assertEqual(len(self.records()), 1)


class SelfTestTests(unittest.TestCase):
    def test_built_in_self_test_is_explicitly_synthetic(self):
        result = engine.self_test()
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["synthetic"])
        self.assertEqual(result["items_checked"], 10)


if __name__ == "__main__":
    unittest.main()
