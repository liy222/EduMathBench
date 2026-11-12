"""Bounded-batch tests use synthetic inputs and patched engines, never APIs."""
import os
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_batch as batch
import eval_engine as engine


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="emb-six-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "data/synthetic"
        (self.data / "inputs").mkdir(parents=True)
        item = {"id": "synthetic-one", "kind": "public", "question": "合成输入，仅用于软件测试。", "options": {x: x for x in "ABCD"}, "split": "dev", "image_assets": []}
        engine.atomic_write(self.data / "inputs/debug_inputs.jsonl", engine.json_bytes(item) + b"\n")
        engine.write_json(self.data / "manifest.json", {"version": "synthetic", "inputs": {"debug": {"path": "inputs/debug_inputs.jsonl", "sha256": engine.file_sha256(self.data / "inputs/debug_inputs.jsonl")}}})
        self.manifest_path = self.root / "config/six.json"
        self.manifest = {"version": "synthetic-six-v1", "stage": "domestic_six_first", "split": "debug", "max_requests_total": 12, "expected_data_manifest_sha256": engine.file_sha256(self.data / "manifest.json"), "models": []}
        self.configs = []
        for number in range(6):
            relative = f"config/models/model-{number}.json"
            cfg = {"data_root": "data/synthetic", "split": "debug", "max_requests": 2, "backend": {"type": "openai-compatible", "model": f"synthetic-{number}", "base_url": "https://provider.example/v1", "api_key_env": f"SYNTHETIC_KEY_{number}", "supports_images": True}, "parameter_mode": "forced_thinking" if number == 2 else "explicit_non_thinking"}
            self.configs.append(cfg)
            engine.write_json(self.root / relative, cfg)
            self.manifest["models"].append({"vendor": f"vendor-{number}", "config": relative, "output_name": f"model-{number}"})
        self.save_manifest()
        self.output = self.root / "output"
        self.keys = {f"SYNTHETIC_KEY_{number}": f"unit-secret-{number}" for number in range(6)}
        self.env_patch = mock.patch.dict(os.environ, self.keys, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def save_manifest(self):
        engine.write_json(self.manifest_path, self.manifest)

    def save_config(self, number):
        engine.write_json(self.root / self.manifest["models"][number]["config"], self.configs[number])

    def check(self, **kwargs):
        return batch.check_batch(self.manifest_path, self.output, project_root=self.root, **kwargs)

    def call_batch(self, **kwargs):
        return batch.run_batch(self.manifest_path, self.output, project_root=self.root, **kwargs)

    def codes(self, report):
        return {row["code"] for row in report["issues"]}

    def test_check_is_answer_blind_and_zero_network_with_hashes(self):
        with mock.patch.object(engine, "call_openai", side_effect=AssertionError("network")), mock.patch.object(engine, "load_answers", side_effect=AssertionError("gold answers")):
            report = self.check()
        self.assertTrue(report["ready_for_api"])
        self.assertEqual(report["external_requests"], 0)
        self.assertEqual(report["account_probe_status"], "not_run")
        self.assertEqual(report["allocated_request_limit"], 12)
        self.assertEqual(report["parameter_modes"]["model-2"], "forced_thinking")
        self.assertEqual(report["models"][0]["dataset"]["input_count"], 1)
        self.assertEqual(len(report["models"][0]["input_order_sha256"]), 64)
        self.assertEqual(len(report["prompt_sha256"]), 64)
        for secret in self.keys.values():
            self.assertNotIn(secret, (self.output / "readiness.json").read_text(encoding="utf-8"))

    def test_missing_credentials_and_budget_block_all_calls(self):
        del os.environ["SYNTHETIC_KEY_5"]
        self.manifest["max_requests_total"] = 0
        self.save_manifest()
        self.configs[0]["max_requests"] = 0
        self.save_config(0)
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not run")), mock.patch.object(engine, "score_run", side_effect=AssertionError("must not score")):
            report = self.call_batch()
        self.assertEqual(report["state"], "blocked_local_prerequisites")
        self.assertEqual(report["external_requests"], 0)
        self.assertTrue({"credential_missing", "batch_budget_required", "model_budget_required"}.issubset(self.codes(report)))

    def test_six_distinct_entries_required(self):
        for field, code in (("vendor", "duplicate_vendor"), ("config", "duplicate_config"), ("output_name", "duplicate_output")):
            with self.subTest(field=field):
                original = self.manifest["models"][1][field]
                self.manifest["models"][1][field] = self.manifest["models"][0][field]
                self.save_manifest()
                self.assertIn(code, self.codes(self.check()))
                self.manifest["models"][1][field] = original
        self.manifest["models"].pop()
        self.save_manifest()
        self.assertIn("six_models_required", self.codes(self.check()))

    def test_duplicate_model_and_request_budget_total(self):
        self.configs[1]["backend"]["model"] = self.configs[0]["backend"]["model"]
        self.save_config(1)
        self.manifest["max_requests_total"] = 11
        self.save_manifest()
        self.assertTrue({"duplicate_model", "batch_budget_exceeded"}.issubset(self.codes(self.check())))

    def test_paths_cannot_escape_project_or_output(self):
        for malicious in ("../external.json", "C:/external.json", "config\\bad.json"):
            with self.subTest(config=malicious):
                self.manifest["models"][0]["config"] = malicious
                self.save_manifest()
                self.assertIn("invalid_config_path", self.codes(self.check()))
        self.manifest["models"][0]["config"] = "config/models/model-0.json"
        for malicious in ("../outside", "", ".hidden", "trailing.", "folder/name", "folder\\name", "-leading"):
            with self.subTest(output=malicious):
                self.manifest["models"][0]["output_name"] = malicious
                self.save_manifest()
                self.assertIn("invalid_output_name", self.codes(self.check()))

    def test_internal_dots_in_actual_model_output_names_are_allowed(self):
        for name in ("qwen3.8-flash", "glm-5.3-flash", "minimax-m3.1-flash", "doubao-seed-2.1-lite", "a"):
            with self.subTest(name=name):
                self.manifest["models"][0]["output_name"] = name
                self.save_manifest()
                self.assertTrue(self.check()["ready_for_api"])

    def test_data_hash_and_dataset_consistency_are_pinned(self):
        self.manifest["expected_data_manifest_sha256"] = "0" * 64
        self.save_manifest()
        self.assertIn("dataset_manifest_mismatch", self.codes(self.check()))
        self.configs[1]["data_root"] = "data/other"
        self.save_config(1)
        self.assertIn("dataset_mismatch", self.codes(self.check()))

    def test_inline_keys_rejected_without_copying_secret(self):
        self.configs[0]["backend"]["api_key"] = "inline-secret-never-print"
        self.save_config(0)
        self.assertIn("invalid_config", self.codes(self.check()))
        self.assertNotIn("inline-secret-never-print", (self.output / "readiness.json").read_text(encoding="utf-8"))

    def test_splits_are_not_overridden_and_test_requires_authorization(self):
        self.manifest["split"] = "test"
        self.save_manifest()
        report = self.check()
        self.assertIn("test_not_authorized", self.codes(report))
        self.assertIn("split_mismatch", self.codes(report))
        self.assertNotIn("test_not_authorized", self.codes(self.check(allow_test=True)))

    def fake_execute(self, config, output, *, resume, allow_test):
        _, data = engine.load_dataset(Path(config["data_root"]), config["split"])
        identity = {"config_sha256": engine.digest(config), "prompt_sha256": engine.digest({"version": engine.PROMPT_VERSION, "system_prompt": engine.SYSTEM_PROMPT}), "input_sha256": data["input_sha256"], "manifest_sha256": data["manifest_sha256"], "split": data["split"]}
        engine.write_json(output / "run.json", {"synthetic_test_fixture": True, "identity": identity})
        return {"run_id": config["backend"]["model"], "synthetic": False, "result_kind": "model_evaluation", "status_counts": {"ok": 1}, "budget_usage": {"remote_request_count": 1}}

    def test_sequential_run_and_resume_pass_fixed_budgets(self):
        with mock.patch.object(engine, "execute_run", side_effect=self.fake_execute) as execute, mock.patch.object(engine, "score_run", return_value={"overall": {"correct": 1, "attempted": 1, "accuracy": 1}}) as score:
            first = self.call_batch()
            self.assertEqual(first["state"], "complete")
            self.assertEqual(first["external_requests"], 6)
            self.assertTrue(first["api_availability_confirmed"])
            self.assertEqual(execute.call_count, 6)
            self.assertEqual(score.call_count, 6)
            for number, call in enumerate(execute.call_args_list):
                self.assertEqual(call.args[0]["backend"]["model"], f"synthetic-{number}")
                self.assertEqual(call.args[0]["max_requests"], 2)
                self.assertEqual(call.args[0]["data_root"], str(self.data.resolve()))
                self.assertFalse(call.kwargs["resume"])
            execute.reset_mock()
            self.call_batch(resume=True)
            self.assertTrue(all(call.kwargs["resume"] for call in execute.call_args_list))

    def test_resume_rejects_any_model_change_before_first_call(self):
        with mock.patch.object(engine, "execute_run", side_effect=self.fake_execute), mock.patch.object(engine, "score_run", return_value={"overall": {}}):
            self.call_batch()
        before = (self.output / "batch.json").read_bytes()
        self.configs[5]["backend"]["temperature"] = 0.5
        self.save_config(5)
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
            with self.assertRaises(engine.EvaluationError):
                self.call_batch(resume=True)
        self.assertEqual((self.output / "batch.json").read_bytes(), before)

    def test_failure_report_does_not_echo_exception_secret(self):
        with mock.patch.object(engine, "execute_run", side_effect=RuntimeError("provider-error unit-secret-0")), mock.patch.object(engine, "score_run") as score:
            report = self.call_batch()
        self.assertEqual(report["state"], "failed")
        self.assertFalse(report["api_availability_confirmed"])
        self.assertEqual(len(report["models"]), 6)
        self.assertTrue(all(row["state"] == "failed" for row in report["models"]))
        self.assertFalse(score.called)
        self.assertNotIn("unit-secret-0", (self.output / "batch_summary.json").read_text(encoding="utf-8"))

    def test_tampered_later_run_is_rejected_before_earlier_requests(self):
        with mock.patch.object(engine, "execute_run", side_effect=self.fake_execute), mock.patch.object(engine, "score_run", return_value={"overall": {}}):
            self.call_batch()
        engine.write_json(self.output / "model-5/run.json", {"identity": {"config_sha256": "foreign"}})
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
            with self.assertRaises(engine.EvaluationError):
                self.call_batch(resume=True)

    def test_unknown_output_files_and_accidental_repeat_block_before_calls(self):
        self.output.mkdir()
        (self.output / "unrelated.txt").write_text("unrelated", encoding="utf-8")
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
            with self.assertRaises(engine.EvaluationError):
                self.call_batch()

    def test_failed_inflight_call_keeps_reserved_request_count(self):
        def fail_after_reservation(config, output, **kwargs):
            engine.write_json(output / "run.json", {"remote_attempts": [{"total_tokens": None, "state": "reserved"}]})
            raise RuntimeError("interrupted")
        with mock.patch.object(engine, "execute_run", side_effect=fail_after_reservation):
            report = self.call_batch()
        self.assertEqual(report["state"], "failed")
        self.assertEqual(report["external_requests"], 6)
        self.assertTrue(report["request_accounting_complete"])

    def test_malformed_split_yields_schema_issue(self):
        self.manifest["split"] = ["debug"]
        self.save_manifest()
        self.assertIn("invalid_split", self.codes(self.check()))

    def test_cli_loads_credentials_but_library_check_leaves_env_alone(self):
        import eval_credentials
        with mock.patch.object(eval_credentials, "load_project_env") as loader, mock.patch.object(batch, "check_batch", return_value={"ready_for_api": True}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(batch.main(["check", "--manifest", str(self.manifest_path), "--output", str(self.output)]), 0)
            loader.assert_called_once_with()
        before = dict(os.environ)
        with mock.patch.object(eval_credentials, "load_project_env", side_effect=AssertionError("library must not load env")):
            self.check()
        self.assertEqual(dict(os.environ), before)

    def test_first_provider_api_errors_do_not_mark_batch_success_or_expand_limits(self):
        def execute(config, output, **kwargs):
            result = self.fake_execute(config, output, **kwargs)
            if config["backend"]["model"] == "synthetic-0":
                result["status_counts"] = {"api_error": 1}
            return result
        with mock.patch.object(engine, "execute_run", side_effect=execute) as remote, mock.patch.object(engine, "score_run", return_value={"overall": {"correct": 0, "attempted": 1}}):
            report = self.call_batch()
        self.assertEqual(remote.call_count, 6)
        self.assertEqual(report["state"], "complete_with_issues")
        self.assertFalse(report["api_availability_confirmed"])
        self.assertFalse(report["models"][0]["api_availability_confirmed"])
        self.assertEqual(report["models"][0]["state"], "complete_with_issues")
        self.assertEqual(report["external_requests"], 6)
        self.assertTrue(all(call.args[0]["max_requests"] == 2 for call in remote.call_args_list))

    def test_concurrent_batch_lock_blocks_every_model_call(self):
        with engine.run_lock(self.output), mock.patch.object(engine, "execute_run", side_effect=AssertionError("locked batch must not call")):
            with self.assertRaises(engine.EvaluationError):
                self.call_batch()

    def add_synthetic_image_item(self):
        path = self.data / "inputs/debug_inputs.jsonl"
        rows = engine.read_jsonl(path)
        image = {**rows[0], "id": "synthetic-image", "question": "合成题目[图1]", "image_assets": [{"path": "assets/fixture.png", "sha256": "0" * 64, "field": "question", "placeholder": "[图1]", "mime_type": "image/png"}]}
        engine.atomic_write(path, b"".join(engine.json_bytes(row) + b"\n" for row in [*rows, image]))
        data_manifest = engine.read_json(self.data / "manifest.json")
        data_manifest["inputs"]["debug"]["sha256"] = engine.file_sha256(path)
        engine.write_json(self.data / "manifest.json", data_manifest)
        self.manifest["expected_data_manifest_sha256"] = engine.file_sha256(self.data / "manifest.json")
        self.save_manifest()

    def test_priority_unknown_in_last_model_blocks_every_request(self):
        self.configs[5]["priority_ids"] = ["unknown-synthetic-id"]
        self.save_config(5)
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
            report = self.call_batch()
        self.assertEqual(report["state"], "blocked_local_prerequisites")
        self.assertIn("invalid_priority_ids", self.codes(report))

    def test_different_final_input_order_blocks_entire_batch(self):
        self.add_synthetic_image_item()
        self.configs[5]["priority_ids"] = ["synthetic-image"]
        self.save_config(5)
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
            report = self.call_batch()
        self.assertIn("input_order_mismatch", self.codes(report))
        self.assertEqual(report["state"], "blocked_local_prerequisites")

    def test_same_priority_order_retains_all_items_and_reports_first_budget_images(self):
        self.add_synthetic_image_item()
        for number in range(6):
            self.configs[number].update(priority_ids=["synthetic-image"], max_requests=1)
            self.save_config(number)
        report = self.check()
        self.assertTrue(report["ready_for_api"])
        self.assertEqual(len({row["input_order_sha256"] for row in report["models"]}), 1)
        for row in report["models"]:
            self.assertEqual(row["dataset"]["input_count"], 2)
            self.assertEqual(row["first_budget_item_count"], 1)
            self.assertEqual(row["first_budget_image_count"], 1)
            self.assertEqual(row["input_order_sha256"], engine.digest(["synthetic-image", "synthetic-one"]))

    def make_targeted_four(self):
        self.manifest.update(stage="domestic_four_retest", max_requests_total=12)
        self.manifest["models"] = self.manifest["models"][:4]
        for number, limit in enumerate((3, 3, 5, 1)):
            self.configs[number]["max_requests"] = limit
            self.save_config(number)
        self.save_manifest()

    def test_targeted_four_run_uses_exact_allocations_and_reports_four(self):
        self.make_targeted_four()
        report = self.check()
        self.assertTrue(report["ready_for_api"])
        self.assertEqual(report["stage"], "domestic_four_retest")
        self.assertEqual(report["expected_model_count"], 4)
        self.assertEqual(report["allocated_request_limit"], 12)
        with mock.patch.object(engine, "execute_run", side_effect=self.fake_execute) as execute, mock.patch.object(engine, "score_run", return_value={"overall": {}}):
            result = self.call_batch()
        self.assertEqual([call.args[0]["max_requests"] for call in execute.call_args_list], [3, 3, 5, 1])
        self.assertEqual(result["state"], "complete")
        self.assertEqual(result["expected_model_count"], 4)
        self.assertTrue(result["api_availability_confirmed"])
        self.assertIn("does not confirm every text/image", result["api_availability_scope"])

    def test_four_entries_are_rejected_for_original_six_stage(self):
        self.make_targeted_four()
        self.manifest["stage"] = "domestic_six_first"
        self.save_manifest()
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
            report = self.call_batch()
        self.assertIn("six_models_required", self.codes(report))
        self.assertEqual(report["state"], "blocked_local_prerequisites")

    def test_targeted_stage_allows_distinct_valid_priority_order(self):
        self.add_synthetic_image_item()
        self.make_targeted_four()
        self.configs[3]["priority_ids"] = ["synthetic-image"]
        self.save_config(3)
        report = self.check()
        self.assertTrue(report["ready_for_api"])
        self.assertEqual(len({row["input_order_sha256"] for row in report["models"]}), 2)

    def test_targeted_total_above_twelve_is_rejected_before_any_call(self):
        self.make_targeted_four()
        self.configs[3]["max_requests"] = 2
        self.save_config(3)
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
            report = self.call_batch()
        self.assertIn("batch_budget_exceeded", self.codes(report))
        self.assertEqual(report["external_requests"], 0)

    def test_other_batch_stages_are_rejected(self):
        self.manifest["stage"] = "arbitrary"
        self.save_manifest()
        self.assertIn("manifest_stage", self.codes(self.check()))

    def test_targeted_unknown_priority_and_missing_pinned_hash_are_rejected(self):
        self.make_targeted_four()
        self.configs[3]["priority_ids"] = ["unknown"]
        self.save_config(3)
        self.manifest.pop("expected_data_manifest_sha256")
        self.save_manifest()
        self.assertTrue({"dataset_hash_required", "invalid_priority_ids"}.issubset(self.codes(self.check())))

    def configure_new_stage(self, stage, *, workers=1):
        split = batch.STAGE_SPLITS[stage]
        if split == "dev":
            source = self.data / "inputs/debug_inputs.jsonl"
            target = self.data / "inputs/dev_inputs.jsonl"
            target.write_bytes(source.read_bytes())
            manifest = engine.read_json(self.data / "manifest.json")
            manifest["inputs"]["dev"] = {"path": "inputs/dev_inputs.jsonl", "sha256": engine.file_sha256(target)}
            engine.write_json(self.data / "manifest.json", manifest)
        self.manifest.update(stage=stage, split=split, parallel_workers=workers)
        self.manifest["models"] = self.manifest["models"][:batch.STAGE_COUNTS[stage]]
        self.manifest["expected_data_manifest_sha256"] = engine.file_sha256(self.data / "manifest.json")
        for number in range(len(self.manifest["models"])):
            self.configs[number]["split"] = split
            self.save_config(number)
        self.save_manifest()

    def test_two_precheck_allows_different_priorities_but_requires_debug_and_hash(self):
        self.add_synthetic_image_item()
        self.configure_new_stage("domestic_two_precheck")
        self.configs[1]["priority_ids"] = ["synthetic-image"]
        self.save_config(1)
        report = self.check()
        self.assertTrue(report["ready_for_api"])
        self.assertEqual(report["expected_model_count"], 2)
        self.assertEqual(len({row["input_order_sha256"] for row in report["models"]}), 2)
        self.manifest.update(split="test")
        self.manifest.pop("expected_data_manifest_sha256")
        self.save_manifest()
        report = self.check(allow_test=True)
        self.assertTrue({"stage_split_mismatch", "dataset_hash_required"}.issubset(self.codes(report)))

    def test_development_stage_requires_dev_even_with_allow_test(self):
        self.manifest.update(stage="domestic_six_development", split="test")
        self.save_manifest()
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
            report = self.call_batch(allow_test=True)
        self.assertEqual(report["state"], "blocked_local_prerequisites")
        self.assertIn("stage_split_mismatch", self.codes(report))

    def test_development_six_requires_matching_complete_input_order(self):
        self.add_synthetic_image_item()
        self.configure_new_stage("domestic_six_development", workers=3)
        self.assertTrue(self.check()["ready_for_api"])
        self.configs[5]["priority_ids"] = ["synthetic-image"]
        self.save_config(5)
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
            report = self.call_batch()
        self.assertIn("input_order_mismatch", self.codes(report))

    def test_parallel_worker_bounds_and_sequential_default(self):
        self.assertEqual(self.check()["parallel_workers"], 1)
        for bad in (0, 4, -1, 1.5, "3", True, None):
            with self.subTest(workers=bad):
                self.manifest["parallel_workers"] = bad
                self.save_manifest()
                with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
                    report = self.call_batch()
                self.assertIn("invalid_parallel_workers", self.codes(report))

    def test_parallel_dev_bounds_order_budget_and_single_summary_writer(self):
        self.configure_new_stage("domestic_six_development", workers=3)
        lock = threading.Lock()
        first_three = threading.Barrier(3)
        active = 0
        maximum = 0
        starts = []
        cap_seen = []
        summary_threads = []
        main_thread = threading.get_ident()
        real_write = engine.write_json

        def tracked_write(path, payload):
            if Path(path).name == "batch_summary.json":
                summary_threads.append(threading.get_ident())
            return real_write(path, payload)

        def execute(config, output, **kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
                starts.append(config["backend"]["model"])
                cap_seen.append(config["max_requests"])
            try:
                if config["backend"]["model"] in {"synthetic-0", "synthetic-1", "synthetic-2"}:
                    first_three.wait(timeout=5)
                # End tasks in a different order; summary must keep manifest order.
                time.sleep(0.005 * (6 - int(config["backend"]["model"].split("-")[-1])))
                result = self.fake_execute(config, output, **kwargs)
                metadata = engine.read_json(output / "run.json")
                metadata["remote_attempts"] = [{"state": "completed", "total_tokens": 1} for _ in range(config["max_requests"])]
                real_write(output / "run.json", metadata)
                result["budget_usage"] = engine.budget_usage(metadata)
                config["backend"]["model"] = "worker-mutated-private-copy"
                return result
            finally:
                with lock:
                    active -= 1

        with mock.patch.object(engine, "execute_run", side_effect=execute), mock.patch.object(engine, "score_run", return_value={"overall": {"correct": 1}}), mock.patch.object(engine, "write_json", side_effect=tracked_write):
            result = self.call_batch()
        self.assertEqual(result["state"], "complete")
        self.assertEqual(maximum, 3)
        self.assertEqual(set(starts[:3]), {"synthetic-0", "synthetic-1", "synthetic-2"})
        self.assertEqual([row["model"] for row in result["models"]], [f"synthetic-{number}" for number in range(6)])
        self.assertEqual(sum(cap_seen), 12)
        self.assertEqual(result["external_requests"], 12)
        self.assertEqual(set(summary_threads), {main_thread})
        self.assertTrue(all(cfg["backend"]["model"] == f"synthetic-{number}" for number, cfg in enumerate(self.configs)))

    def test_parallel_single_failure_retains_other_results_and_sanitizes(self):
        self.configure_new_stage("domestic_six_development", workers=3)
        def execute(config, output, **kwargs):
            if config["backend"]["model"] == "synthetic-1":
                raise RuntimeError("private-provider-error unit-secret-1")
            result = self.fake_execute(config, output, **kwargs)
            if config["backend"]["model"] == "synthetic-3":
                result["status_counts"] = {"api_error": 1}
            return result
        with mock.patch.object(engine, "execute_run", side_effect=execute) as remote, mock.patch.object(engine, "score_run", return_value={"overall": {}}):
            result = self.call_batch()
        self.assertEqual(remote.call_count, 6)
        self.assertEqual(result["state"], "failed")
        self.assertFalse(result["api_availability_confirmed"])
        self.assertEqual(result["models"][1]["state"], "failed")
        self.assertEqual(result["models"][3]["state"], "complete_with_issues")
        self.assertEqual(result["models"][5]["state"], "complete")
        self.assertNotIn("unit-secret-1", (self.output / "batch_summary.json").read_text(encoding="utf-8"))

    def test_parallel_resume_checks_all_run_identities_before_submitting(self):
        self.configure_new_stage("domestic_six_development", workers=3)
        with mock.patch.object(engine, "execute_run", side_effect=self.fake_execute), mock.patch.object(engine, "score_run", return_value={"overall": {}}):
            self.call_batch()
        with mock.patch.object(engine, "execute_run", side_effect=self.fake_execute) as remote, mock.patch.object(engine, "score_run", return_value={"overall": {}}):
            self.call_batch(resume=True)
        self.assertTrue(all(call.kwargs["resume"] for call in remote.call_args_list))
        engine.write_json(self.output / "model-5/run.json", {"identity": {"foreign": True}})
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
            with self.assertRaises(engine.EvaluationError):
                self.call_batch(resume=True)

    def test_changing_parallel_workers_refuses_resume_via_manifest_hash(self):
        with mock.patch.object(engine, "execute_run", side_effect=self.fake_execute), mock.patch.object(engine, "score_run", return_value={"overall": {}}):
            self.call_batch()
        self.manifest["parallel_workers"] = 2
        self.save_manifest()
        with mock.patch.object(engine, "execute_run", side_effect=AssertionError("must not call")):
            with self.assertRaises(engine.EvaluationError):
                self.call_batch(resume=True)


if __name__ == "__main__":
    unittest.main()
