"""Campaign controller tests use generated files and mocked batch calls only."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_engine as engine
import run_development_campaign as campaign


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="emb-campaign-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "runs/campaign_1000"
        self.path = self.root / "config/evaluation_campaign_1000.json"
        self.value = {"version": "synthetic-campaign-v1", "authorized_max_requests": 1000, "allocated_max_requests": 998, "stages": []}
        names = ["kimi-k3", "deepseek-flash", "qwen3.8-flash", "glm-5.3-flash", "minimax-m3.1-flash", "doubao-seed-2.1-lite"]
        for name, stage, split, cap, total, models in (
            ("precheck", "domestic_two_precheck", "debug", 4, 8, ["qwen3.8-flash", "minimax-m3.1-flash"]),
            ("development", "domestic_six_development", "dev", 165, 990, names),
        ):
            manifest = {"stage": stage, "split": split, "max_requests_total": total, "models": []}
            for model in models:
                relative = f"config/synthetic/{name}/{model}.json"
                engine.write_json(self.root / relative, {"max_requests": cap, "split": split, "backend": {"model": model}})
                manifest["models"].append({"vendor": model, "output_name": model, "config": relative})
            relative = f"config/synthetic_{name}.json"
            engine.write_json(self.root / relative, manifest)
            self.value["stages"].append({"name": name, "manifest": relative, "output": f"runs/campaign_1000/{name}", "max_requests": total})
        self.save()
        for attr, value in (("ROOT", self.root), ("CAMPAIGN", self.path), ("OUT", self.out)):
            patcher = mock.patch.object(campaign, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.loader = mock.patch.object(campaign, "load_project_env", return_value={}).start()
        self.addCleanup(mock.patch.stopall)
        self.checker = mock.patch.object(campaign.eval_batch, "check", side_effect=self.fake_check).start()
        self.snapshot = mock.patch.object(campaign, "snapshot").start()
        mock.patch.object(engine, "call_openai", side_effect=AssertionError("No external network is allowed in these tests")).start()

    def save(self):
        engine.write_json(self.path, self.value)

    def manifest(self, index):
        return engine.read_json(self.root / self.value["stages"][index]["manifest"])

    def save_manifest(self, index, manifest):
        engine.write_json(self.root / self.value["stages"][index]["manifest"], manifest)

    def fake_check(self, manifest_path, output):
        manifest = engine.read_json(manifest_path)
        allocation = sum(engine.read_json(self.root / row["config"])["max_requests"] for row in manifest["models"])
        return {"ready_for_api": True, "allocated_request_limit": allocation}

    def detail(self, *, status="ok", finish="stop", padded=True):
        return {"status": status, "attempts": [{"status": "received", "raw_response": {"choices": [{"finish_reason": finish}]}}], "image_processing": [{"source_dimensions": [8, 35], "derived_dimensions": [32 if padded else 8, 35]} for _ in range(4)]}

    def write_details(self, output, *, qwen_finish="stop", minimax_padded=True):
        for name in ("qwen3.8-flash", "minimax-m3.1-flash"):
            detail = self.detail(finish=qwen_finish if name.startswith("qwen") else "stop", padded=minimax_padded if name.startswith("minimax") else True)
            engine.write_json(output / name / "items" / engine.item_filename(campaign.PROBLEM), detail)

    def write_metadata(self, stage_index, counts, *, reserved=0):
        stage = self.value["stages"][stage_index]
        for row, count in zip(self.manifest(stage_index)["models"], counts):
            reservations = [{"state": "reserved" if number < reserved else "completed", "total_tokens": None} for number in range(count)]
            engine.write_json(self.root / stage["output"] / row["output_name"] / "run.json", {"remote_attempts": reservations})

    def fake_run(self, manifest_path, output, *, resume):
        manifest = engine.read_json(manifest_path)
        engine.write_json(output / "batch.json", {"fixture": True})
        index = 0 if manifest["stage"] == "domestic_two_precheck" else 1
        self.write_metadata(index, [1] * len(manifest["models"]))
        if index == 0:
            self.write_details(output)
        return {"state": "complete"}

    def test_precheck_gate_rejects_qwen_length_and_minimax_image_failure(self):
        output = self.out / "precheck"
        self.write_details(output)
        self.assertTrue(campaign.precheck_gate(output)["passed"])
        self.write_details(output, qwen_finish="length")
        result = campaign.precheck_gate(output)
        self.assertFalse(result["passed"])
        self.assertTrue(result["goals"]["qwen3.8-flash"]["truncated"])
        self.write_details(output, minimax_padded=False)
        result = campaign.precheck_gate(output)
        self.assertFalse(result["passed"])
        self.assertFalse(result["goals"]["minimax-m3.1-flash"]["small_images_padded"])

    def test_qwen_truncation_blocks_development_and_persists_stop(self):
        def run(manifest_path, output, **kwargs):
            result = self.fake_run(manifest_path, output, **kwargs)
            self.write_details(output, qwen_finish="length")
            return result
        with mock.patch.object(campaign.eval_batch, "run_batch", side_effect=run) as runner:
            result = campaign.run()
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(result["state"], "stopped_precheck_failed")
        self.assertEqual(engine.read_json(self.out / "campaign.json")["state"], "stopped_precheck_failed")
        self.assertEqual(result["accounting"]["new_requests"], 2)

    def test_minimax_failed_padding_blocks_development(self):
        def run(manifest_path, output, **kwargs):
            result = self.fake_run(manifest_path, output, **kwargs)
            self.write_details(output, minimax_padded=False)
            return result
        with mock.patch.object(campaign.eval_batch, "run_batch", side_effect=run) as runner:
            result = campaign.run()
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(result["state"], "stopped_precheck_failed")

    def test_missing_precheck_evidence_stops_cleanly(self):
        def run(manifest_path, output, **kwargs):
            engine.write_json(output / "batch.json", {"fixture": True})
            return {"state": "complete"}
        with mock.patch.object(campaign.eval_batch, "run_batch", side_effect=run) as runner:
            result = campaign.run()
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(result["state"], "stopped_precheck_failed")

    def test_success_runs_precheck_then_development_and_counts_both(self):
        with mock.patch.object(campaign.eval_batch, "run_batch", side_effect=self.fake_run) as runner:
            result = campaign.run()
        self.assertEqual([engine.read_json(call.args[0])["stage"] for call in runner.call_args_list], ["domestic_two_precheck", "domestic_six_development"])
        self.assertTrue(result["precheck_gate"]["passed"])
        self.assertEqual(result["state"], "development_finished_pending_protocol_audit")
        self.assertEqual(result["accounting"]["by_stage"], {"precheck": 2, "development": 6})
        self.assertEqual(result["accounting"]["new_requests"], 8)
        self.assertEqual(self.checker.call_count, 2)
        self.loader.assert_called_once_with()

    def test_persistent_reserved_attempts_count_towards_total_and_inflight(self):
        self.write_metadata(0, [4, 4], reserved=1)
        self.write_metadata(1, [165] * 6, reserved=1)
        result = campaign.request_accounting(self.value)
        self.assertEqual(result["new_requests"], 998)
        self.assertEqual(result["by_stage"], {"precheck": 8, "development": 990})
        self.assertEqual(result["inflight"], 8)
        self.assertEqual(result["cumulative_requests"], 72 + 998)

    def test_accounting_rejects_per_model_stage_and_campaign_overruns(self):
        self.write_metadata(0, [5, 0])
        with self.assertRaisesRegex(engine.EvaluationError, "Per-model"):
            campaign.request_accounting(self.value)
        self.write_metadata(0, [4, 4])
        reduced = copy.deepcopy(self.value)
        reduced["stages"][0]["max_requests"] = 7
        with self.assertRaisesRegex(engine.EvaluationError, "Stage"):
            campaign.request_accounting(reduced)
        self.write_metadata(1, [165] * 6)
        reduced = copy.deepcopy(self.value)
        reduced["authorized_max_requests"] = 997
        with self.assertRaisesRegex(engine.EvaluationError, "Campaign"):
            campaign.request_accounting(reduced)

    def test_resume_changed_last_model_identity_prevents_all_batch_calls(self):
        with mock.patch.object(campaign.eval_batch, "run_batch", side_effect=self.fake_run):
            campaign.run()
        cfg_path = self.root / self.manifest(1)["models"][-1]["config"]
        cfg = engine.read_json(cfg_path)
        cfg["frozen_parameter_changed"] = True
        engine.write_json(cfg_path, cfg)
        with mock.patch.object(campaign.eval_batch, "run_batch", side_effect=AssertionError("must not send")) as runner:
            with self.assertRaisesRegex(engine.EvaluationError, "unchanged identity"):
                campaign.run(resume=True)
        self.assertFalse(runner.called)

    def test_resume_unchanged_passes_resume_to_both_batches(self):
        with mock.patch.object(campaign.eval_batch, "run_batch", side_effect=self.fake_run):
            campaign.run()
        with mock.patch.object(campaign.eval_batch, "run_batch", side_effect=self.fake_run) as runner:
            campaign.run(resume=True)
        self.assertEqual(runner.call_count, 2)
        self.assertTrue(all(call.kwargs["resume"] for call in runner.call_args_list))

    def test_manifest_stage_cap_above_campaign_allocation_blocks_before_calls(self):
        manifest = self.manifest(0)
        manifest["max_requests_total"] = 9
        self.save_manifest(0, manifest)
        with mock.patch.object(campaign.eval_batch, "run_batch", side_effect=AssertionError("must not send")) as runner:
            with self.assertRaisesRegex(engine.EvaluationError, "limits exceed"):
                campaign.run()
        self.assertFalse(runner.called)

    def test_stage_order_and_wrong_split_are_rejected_before_calls(self):
        self.value["stages"].reverse()
        self.save()
        with mock.patch.object(campaign.eval_batch, "run_batch", side_effect=AssertionError("must not send")):
            with self.assertRaisesRegex(engine.EvaluationError, "precheck then development"):
                campaign.run()
        self.value["stages"].reverse()
        self.save()
        manifest = self.manifest(1)
        manifest["split"] = "test"
        self.save_manifest(1, manifest)
        with mock.patch.object(campaign.eval_batch, "run_batch", side_effect=AssertionError("must not send")):
            with self.assertRaisesRegex(engine.EvaluationError, "stage/split"):
                campaign.run()


if __name__ == "__main__":
    unittest.main()
