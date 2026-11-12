"""Offline protocol regressions using an isolated, entirely generated campaign.

No fixture is a model result. Metadata uses ``synthetic=False`` solely to test
the audit's real-result schema, inside a temporary directory that is deleted.
Nothing is copied into the actual campaign/reports; APIs and dotenv are unused.
"""
import base64
import copy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_engine as engine
import freeze_development_protocol as audit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NAMES = ["kimi-k3", "deepseek-flash", "qwen3.8-flash", "glm-5.3-flash", "minimax-m3.1-flash", "doubao-seed-2.1-lite"]
PROBLEM = "EMB-P-WEB2-TIKU-1754090"
FROZEN = {"frozen", "frozen_with_observed_model_failures"}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(engine.json_bytes(value) + b"\n")


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(engine.json_bytes(row) + b"\n" for row in rows))


def png(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\xff\xff" * width) * height)) + chunk(b"IEND", b"")


def make_fixture(root):
    """Build 2xdebug100 (4 requested each), 6xdev150, and source snapshots."""
    data = root / "data/fixture"
    source, derived = png(8, 35), png(32, 35)
    asset = data / "assets/fixture.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(source)
    source_sha = engine.file_sha256(asset)
    derived_sha = __import__("hashlib").sha256(derived).hexdigest()
    rows = []
    for number in range(150):
        identifier = PROBLEM if number == 0 else f"fixture-{number:03}"
        row = {"id": identifier, "review_no": number + 1, "kind": "public", "grade": 7 + number // 50, "module": "synthetic-fixture", "difficulty": "synthetic-fixture", "question": "软件回归夹具，请选择A。", "options": {x: x for x in "ABCD"}, "image_assets": [], "split": "dev", "parent_id": None, "family_id": identifier}
        if number == 0:
            row["options"] = {x: f"选项{x}[图{x}]" for x in "ABCD"}
            row["image_assets"] = [{"path": "assets/fixture.png", "sha256": source_sha, "mime_type": "image/png", "field": f"options.{x}", "placeholder": f"[图{x}]"} for x in "ABCD"]
        rows.append(row)
    manifest = {"version": "isolated-audit-unit-fixture", "status": "synthetic-fixture", "inputs": {}, "answers": {}}
    for split, selected in (("debug", rows[:100]), ("dev", rows)):
        inp, ans = data / f"inputs/{split}_inputs.jsonl", data / f"answers/{split}_answers.jsonl"
        write_rows(inp, selected)
        write_rows(ans, [{"id": q["id"], "answer": "A"} for q in selected])
        manifest["inputs"][split] = {"path": f"inputs/{split}_inputs.jsonl", "sha256": engine.file_sha256(inp)}
        manifest["answers"][split] = {"path": f"answers/{split}_answers.jsonl", "sha256": engine.file_sha256(ans)}
    write(data / "manifest.json", manifest)
    for script in ("eval_engine.py", "eval_batch.py", "eval_credentials.py", "run_development_campaign.py"):
        target = root / "scripts" / script
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / "scripts" / script, target)
    campaign = {"version": "isolated-audit-unit-fixture", "authorized_max_requests": 1000, "allocated_max_requests": 998, "unallocated_reserve": 2, "previous_authorized_requests": 72, "formal_test_authorized": False, "stages": []}
    prompt_sha = engine.digest({"version": engine.PROMPT_VERSION, "system_prompt": engine.SYSTEM_PROMPT})
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stage_records = []
    for stage_name, stage_type, split, count, limit, total, models in (
        ("precheck", "domestic_two_precheck", "debug", 100, 4, 8, ["qwen3.8-flash", "minimax-m3.1-flash"]),
        ("development", "domestic_six_development", "dev", 150, 165, 990, NAMES),
    ):
        stage_out = root / f"runs/campaign_1000/{stage_name}"
        stage_manifest = {"version": "isolated-audit-unit-fixture", "stage": stage_type, "split": split, "max_requests_total": total, "parallel_workers": 1 if split == "debug" else 3, "expected_data_manifest_sha256": engine.file_sha256(data / "manifest.json"), "models": []}
        plans, summaries = [], []
        for name in models:
            model_id = "MiniMax-M3.1-Flash" if name.startswith("minimax") else ("doubao-seed-2-1-lite-260915" if name.startswith("doubao") else name)
            declared = {"data_root": "data/fixture", "split": split, "priority_ids": [PROBLEM], "max_requests": limit, "parameter_mode": "isolated_fixture", "backend": {"type": "openai-compatible", "model": model_id, "base_url": "https://fixture.invalid/v1", "api_key_env": "NEVER_READ_THIS_FIXTURE_KEY", "temperature": 0, "supports_images": True, "max_output_tokens": 8192, "minimum_image_dimension": 32, "request_interval_seconds": 21 if name == "kimi-k3" else 1}}
            relative = f"config/campaign_1000/{stage_name}/{name}.json"
            write(root / relative, declared)
            config = copy.deepcopy(declared)
            config["data_root"] = str(data)
            config = engine.normalize_config(config)
            items, dataset = engine.load_dataset(data, split)
            ident = {"config_sha256": engine.digest(config), "input_sha256": dataset["input_sha256"], "manifest_sha256": dataset["manifest_sha256"], "prompt_sha256": prompt_sha, "split": split}
            run_id = f"isolated-fixture-{stage_name}-{name}"
            folder = stage_out / name
            predictions, reservations = [], []
            for index, item in enumerate(items):
                asked = split == "dev" or index < 4
                instant = (base_time + timedelta(seconds=index * (21 if name == "kimi-k3" else 1))).isoformat()
                detail = {"id": item["id"], "run_id": run_id, "synthetic": False, "complete": True, "attempted": asked, "status": "ok" if asked else "unrun_budget_limit", "answer": "A" if asked else None, "attempt_count": int(asked), "attempts": [], "usage": {"total_tokens": 3} if asked else {}, "latency_seconds": 1 if asked else 0, "finished_at": instant}
                blocks = []
                if item["image_assets"]:
                    detail["image_processing"] = [{"path": "assets/fixture.png", "source_sha256": source_sha, "derived_sha256": derived_sha, "source_dimensions": [8, 35], "derived_dimensions": [32, 35], "operation": "white_padding", "padding_color": "white", "padding": {"left": 12, "top": 0, "right": 12, "bottom": 0}, "pillow_version": "isolated-fixture"} for _ in range(4)]
                    for a in item["image_assets"]:
                        blocks.extend([{"type": "text", "text": f"题图对应字段 {a['field']}，占位符 {a['placeholder']}："}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(derived).decode()}}])
                detail["raw_request"] = engine.build_request(item, config["backend"], blocks)
                if asked:
                    reservation_id = f"{run_id}-reservation-{index}"
                    response = {"choices": [{"message": {"role": "assistant", "content": "最终答案：A"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}
                    detail["attempts"] = [{"attempt": 1, "status": "received", "started_at": instant, "latency_seconds": 1, "http_status": 200, "retryable": False, "raw_response": response, "budget_reservation_id": reservation_id}]
                    detail["response_text"] = "最终答案：A"
                    reservations.append({"reservation_id": reservation_id, "item_id": item["id"], "attempt": 1, "started_at": instant, "state": "completed", "total_tokens": 3})
                else:
                    detail["budget_limit_reason"] = "max_requests"
                write(folder / "items" / engine.item_filename(item["id"]), detail)
                predictions.append(engine.summary_record(detail))
            meta = {"schema_version": 1, "run_id": run_id, "synthetic": False, "result_kind": "model_evaluation", "config": config, "identity": ident, "dataset": dataset, "state": "complete" if split == "dev" else "budget_exhausted", "remote_attempts": reservations, "budget_usage": engine.budget_usage({"remote_attempts": reservations}), "engine_sha256": engine.file_sha256(root / "scripts/eval_engine.py"), "prompt_version": engine.PROMPT_VERSION, "system_prompt": engine.SYSTEM_PROMPT, "completed_count": count}
            write(folder / "run.json", meta)
            write_rows(folder / "predictions.jsonl", predictions)
            engine.score_run(folder)
            write(folder / "run_summary.json", {"run_id": run_id, "synthetic": False, "result_kind": "model_evaluation", "input_count": count, "completed_count": count, "status_counts": engine.counts([r["status"] for r in predictions]), "budget_usage": meta["budget_usage"], "budget_unrun_count": 0 if split == "dev" else 96})
            stage_manifest["models"].append({"vendor": name, "output_name": name, "config": relative})
            plans.append({"output_name": name, "config_sha256": ident["config_sha256"], "dataset": dataset, "input_order_sha256": engine.digest([r["id"] for r in items])})
            summaries.append({"output_name": name, "state": "complete" if split == "dev" else "complete_with_issues"})
        manifest_relative = f"config/evaluation_{'precheck' if split == 'debug' else 'dev150'}_1000.json"
        write(root / manifest_relative, stage_manifest)
        batch_ident = {"batch_manifest_sha256": engine.file_sha256(root / manifest_relative), "prompt_sha256": prompt_sha, "models": plans}
        write(stage_out / "batch.json", {"state": "complete" if split == "dev" else "complete_with_issues", "identity": batch_ident})
        write(stage_out / "batch_summary.json", {"state": "complete" if split == "dev" else "complete_with_issues", "identity": batch_ident, "stage": stage_type, "models": summaries})
        campaign["stages"].append({"name": stage_name, "manifest": manifest_relative, "output": f"runs/campaign_1000/{stage_name}", "max_requests": total})
        stage_records.append({"manifest": manifest_relative, "sha256": engine.file_sha256(root / manifest_relative), "configs": [{"path": e["config"], "sha256": engine.file_sha256(root / e["config"])} for e in stage_manifest["models"]]})
    campaign_path = root / audit.DEFAULT_CAMPAIGN
    write(campaign_path, campaign)
    output = root / "runs/campaign_1000"
    write(output / "campaign.json", {"state": "development_finished_pending_protocol_audit", "authorized_max_requests": 1000, "identity": {"campaign_sha256": engine.file_sha256(campaign_path), "stages": stage_records, "prompt_sha256": prompt_sha}})
    write(output / "precheck_gate.json", {"passed": True})
    write(output / "campaign_summary.json", {"state": "development_finished_pending_protocol_audit", "precheck_gate": {"passed": True}, "accounting": {"new_requests": 908, "by_stage": {"precheck": 8, "development": 900}, "inflight": 0, "authorized_max_requests": 1000, "previous_requests": 72, "cumulative_requests": 980}})
    for stage in campaign["stages"]:
        mf = engine.read_json(root / stage["manifest"])
        paths = ["scripts/eval_engine.py", "scripts/eval_batch.py", "scripts/eval_credentials.py", "scripts/run_development_campaign.py", audit.DEFAULT_CAMPAIGN, stage["manifest"], *[m["config"] for m in mf["models"]]]
        target = output / "implementation" / stage["name"]
        records = []
        for relative in paths:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / relative, destination)
            records.append({"path": relative, "sha256": engine.file_sha256(destination)})
        write(target / "snapshot_manifest.json", {"files": records, "credentials_copied": False})
    write(output / "implementation/implementation_index.json", {"version": "isolated-audit-unit-fixture", "stages": {s["name"]: [{"directory": f"runs/campaign_1000/implementation/{s['name']}", "scope": "initial"}] for s in campaign["stages"]}})
    return campaign


class FreezeProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="emb-isolated-freeze-fixture-")
        cls.root = Path(cls.temp.name)
        cls.campaign = make_fixture(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.restore = {}
        self.root_patch = mock.patch.object(audit, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.network_patch = mock.patch.object(engine, "call_openai", side_effect=AssertionError("No network: isolated offline audit fixture"))
        self.network_patch.start()
        self.addCleanup(self.network_patch.stop)
        self.old_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.old_cwd)

    def tearDown(self):
        for path, payload in self.restore.items():
            if payload is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)

    def preserve(self, path):
        if path not in self.restore:
            self.restore[path] = path.read_bytes() if path.exists() else None
        return path

    def edit(self, path, fn):
        self.preserve(path)
        obj = engine.read_json(path)
        fn(obj)
        write(path, obj)

    def run_dir(self, name="deepseek-flash", stage="development"):
        return self.root / "runs/campaign_1000" / stage / name

    def report(self):
        stages = [audit.load_stage(spec) for spec in self.campaign["stages"]]
        return audit.compare_and_audit(self.campaign, stages)

    def assertNotFrozen(self, result):
        self.assertNotIn(result["state"], FROZEN, result.get("issues"))

    def change_detail(self, name, fn, *, change_meta=None, score=True):
        folder = self.run_dir(name)
        path = folder / "items" / engine.item_filename(PROBLEM)
        self.edit(path, fn)
        rows_path = self.preserve(folder / "predictions.jsonl")
        rows = engine.read_jsonl(rows_path)
        detail = engine.read_json(path)
        rows = [engine.summary_record(detail) if row["id"] == PROBLEM else row for row in rows]
        write_rows(rows_path, rows)
        if change_meta:
            self.edit(folder / "run.json", change_meta)
        if score:
            self.preserve(folder / "score.json")
            engine.score_run(folder)

    def test_complete_fixture_counts_precheck_eight_and_dev_150_denominators(self):
        result = self.report()
        self.assertIn(result["state"], FROZEN, result.get("issues"))
        self.assertEqual(result["precheck_requests"], 8)
        self.assertEqual(result["development_requests"], 900)
        self.assertEqual(result["new_campaign_requests"], 908)
        self.assertEqual(result["formal_test_requests"], 0)
        for model in result["development"]:
            self.assertEqual(model["attempted"], 150)
            self.assertEqual(model["correct"], 150)
            self.assertEqual(model["accuracy_correct_over_attempted_dev_only"], 1)

    def test_missing_score_does_not_freeze(self):
        self.preserve(self.run_dir() / "score.json").unlink()
        self.assertNotFrozen(self.report())

    def test_changed_score_denominator_does_not_freeze(self):
        self.edit(self.run_dir() / "score.json", lambda score: score["overall"].update(attempted=149, accuracy=150 / 149))
        self.assertNotFrozen(self.report())

    def test_changed_score_identity_does_not_freeze(self):
        self.edit(self.run_dir() / "score.json", lambda score: score["identity"].update(config_sha256="0" * 64))
        self.assertNotFrozen(self.report())

    def test_internally_consistent_but_wrong_correct_score_does_not_freeze(self):
        self.edit(self.run_dir() / "score.json", lambda score: score["overall"].update(correct=149, accuracy=149 / 150, accuracy_among_parsed=149 / 150))
        self.assertNotFrozen(self.report())

    def test_changed_answer_provenance_in_score_does_not_freeze(self):
        self.edit(self.run_dir() / "score.json", lambda score: score["answer_tables"][0].update(sha256="0" * 64))
        self.assertNotFrozen(self.report())

    def test_external_cwd_resolves_declared_config_against_project_root(self):
        os.chdir(PROJECT_ROOT)
        result = self.report()
        self.assertIn(result["state"], FROZEN, result.get("issues"))

    def test_historical_http_retry_with_final_ok_is_observation_not_blocker(self):
        folder = self.run_dir()
        original = engine.read_json(folder / "items" / engine.item_filename(PROBLEM))
        reservation = original["attempts"][0]["budget_reservation_id"]
        retry_id = reservation + "-retry"
        def detail_change(detail):
            received = copy.deepcopy(detail["attempts"][0])
            error = {**copy.deepcopy(received), "status": "api_error", "http_status": 429, "retryable": True, "raw_response": {"error": "isolated retry fixture"}}
            received.update(attempt=2, budget_reservation_id=retry_id)
            detail.update(attempt_count=2, latency_seconds=2, attempts=[error, received])
        def meta_change(meta):
            retry = copy.deepcopy(meta["remote_attempts"][0])
            retry.update(reservation_id=retry_id, attempt=2)
            meta["remote_attempts"][0]["total_tokens"] = None
            meta["remote_attempts"].insert(1, retry)
            meta["budget_usage"] = engine.budget_usage(meta)
        self.change_detail("deepseek-flash", detail_change, change_meta=meta_change)
        result = self.report()
        self.assertIn(result["state"], FROZEN, result.get("issues"))
        self.assertEqual(result["new_campaign_requests"], 909)
        model = next(m for m in result["development"] if m["output_name"] == "deepseek-flash")
        self.assertEqual(model["http_error_groups"].get("429"), 1)
        self.assertEqual(model["attempted"], 150)

    def test_final_api_error_cannot_freeze(self):
        def change(detail):
            detail.update(status="api_error", answer=None)
            detail["attempts"][-1].update(status="api_error", http_status=403, raw_response={"error": "isolated permission fixture"})
        self.change_detail("deepseek-flash", change)
        self.assertNotFrozen(self.report())

    def test_parse_failure_preserves_attempted_150_and_separate_coverage(self):
        def change(detail):
            detail.update(status="parse_failure", answer=None, response_text="", parse_reason="empty_response")
            detail["attempts"][-1]["raw_response"]["choices"][0].update(finish_reason="length", message={"content": ""})
        self.change_detail("deepseek-flash", change)
        result = self.report()
        self.assertEqual(result["state"], "frozen_with_observed_model_failures", result.get("issues"))
        model = next(m for m in result["development"] if m["output_name"] == "deepseek-flash")
        self.assertEqual(model["attempted"], 150)
        self.assertEqual(model["correct"], 149)
        self.assertEqual(model["accuracy_correct_over_attempted_dev_only"], 149 / 150)
        self.assertEqual(model["accuracy_among_parsed_dev_only"], 1)
        self.assertEqual(model["answer_coverage_dev_only"], 149 / 150)
        self.assertEqual(model["observed_failure_count"], 1)

    def test_unrun_item_cannot_be_counted_as_complete_or_zero_failure(self):
        def change(detail):
            detail.update(status="unrun_budget_limit", answer=None, attempted=False, attempts=[], attempt_count=0, budget_limit_reason="max_requests")
        self.change_detail("deepseek-flash", change)
        self.assertNotFrozen(self.report())

    def test_input_hash_change_cannot_freeze(self):
        path = self.preserve(self.root / "data/fixture/inputs/dev_inputs.jsonl")
        rows = engine.read_jsonl(path)
        rows[1]["question"] += " changed"
        write_rows(path, rows)
        self.assertNotFrozen(self.report())

    def test_stage_manifest_pin_change_cannot_freeze(self):
        relative = self.campaign["stages"][1]["manifest"]
        self.edit(self.root / relative, lambda mf: mf.update(expected_data_manifest_sha256="0" * 64))
        self.assertNotFrozen(self.report())

    def test_declared_config_change_cannot_freeze(self):
        manifest = engine.read_json(self.root / self.campaign["stages"][1]["manifest"])
        relative = next(m["config"] for m in manifest["models"] if m["output_name"] == "deepseek-flash")
        self.edit(self.root / relative, lambda cfg: cfg["backend"].update(temperature=0.5))
        self.assertNotFrozen(self.report())

    def test_prompt_hash_change_cannot_freeze(self):
        self.edit(self.run_dir() / "run.json", lambda meta: meta["identity"].update(prompt_sha256="0" * 64))
        self.assertNotFrozen(self.report())

    def test_unknown_precheck_split_does_not_report_test_zero(self):
        self.edit(self.run_dir("qwen3.8-flash", "precheck") / "run.json", lambda meta: meta["config"].update(split="test"))
        result = self.report()
        self.assertNotFrozen(result)
        self.assertNotEqual(result["formal_test_requests"], 0)

    def test_missing_reservations_are_unknown_not_zero(self):
        self.edit(self.run_dir() / "run.json", lambda meta: meta.pop("remote_attempts"))
        result = self.report()
        self.assertNotFrozen(result)
        self.assertIsNone(result["new_campaign_requests"])

    def test_duplicate_or_missing_dev_id_does_not_freeze(self):
        path = self.preserve(self.run_dir() / "predictions.jsonl")
        rows = engine.read_jsonl(path)
        rows[-1] = copy.deepcopy(rows[-2])
        write_rows(path, rows)
        self.assertNotFrozen(self.report())

    def test_journal_answer_must_match_raw_detail(self):
        path = self.preserve(self.run_dir() / "predictions.jsonl")
        rows = engine.read_jsonl(path)
        rows[0]["answer"] = "B"
        write_rows(path, rows)
        self.assertNotFrozen(self.report())

    def test_orphan_reserved_request_blocks_freezing_and_remains_counted(self):
        def change(meta):
            meta["remote_attempts"].append({"reservation_id": "orphan-fixture", "item_id": PROBLEM, "state": "reserved", "total_tokens": None})
        self.edit(self.run_dir() / "run.json", change)
        result = self.report()
        self.assertNotFrozen(result)
        self.assertEqual(result["new_campaign_requests"], 909)

    def test_missing_run_metadata_is_unknown_not_zero_formal_test_claim(self):
        self.preserve(self.run_dir() / "run.json").unlink()
        result = self.report()
        self.assertNotFrozen(result)
        self.assertIsNone(result["new_campaign_requests"])
        self.assertIsNone(result["formal_test_requests"])

    def test_modified_source_snapshot_does_not_freeze(self):
        path = self.preserve(self.root / "runs/campaign_1000/implementation/development/scripts/eval_engine.py")
        path.write_bytes(path.read_bytes() + b"\n# isolated snapshot tamper\n")
        self.assertNotFrozen(self.report())

    def test_modified_config_snapshot_does_not_freeze(self):
        folder = self.root / "runs/campaign_1000/implementation/development"
        manifest = engine.read_json(self.root / self.campaign["stages"][1]["manifest"])
        relative = next(m["config"] for m in manifest["models"] if m["output_name"] == "deepseek-flash")
        self.edit(folder / relative, lambda cfg: cfg["backend"].update(temperature=0.5))
        self.assertNotFrozen(self.report())

    def test_missing_snapshot_index_is_not_evidence_for_freezing_new_campaign(self):
        self.preserve(self.root / "runs/campaign_1000/implementation/implementation_index.json").unlink()
        self.assertNotFrozen(self.report())

    def add_checkpoint_orphans(self):
        """Model the three real interrupted requests without fabricating results."""
        pending = []
        for name in ("deepseek-flash", "qwen3.8-flash", "glm-5.3-flash"):
            rid = f"isolated-interrupted-{name}"
            def add(meta, rid=rid):
                meta["remote_attempts"].append({"reservation_id": rid, "item_id": PROBLEM, "attempt": 1, "state": "interrupted_unknown", "total_tokens": None, "started_at": "2026-01-01T00:00:00+00:00"})
                meta["budget_usage"] = engine.budget_usage(meta)
            self.edit(self.run_dir(name) / "run.json", add)
            self.preserve(self.run_dir(name) / "score.json")
            engine.score_run(self.run_dir(name))
            pending.append({"reservation_id": rid, "stage": "development", "model": name, "item_id": PROBLEM, "state": "reserved"})
        path = self.preserve(self.root / "runs/campaign_1000/io_interruption_checkpoint.json")
        value = {"fixture_notice": "Generated offline checkpoint, not a real model call.", "accounting": {"new_requests": 275}, "pending": pending}
        write(path, value)
        return path, value

    def add_implementation_snapshot(self, suffix, scope):
        initial = self.root / "runs/campaign_1000/implementation/development"
        directory = self.root / f"runs/campaign_1000/implementation/development_{suffix}"
        manifest = engine.read_json(initial / "snapshot_manifest.json")
        for row in manifest["files"]:
            path = self.preserve(directory / row["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = (initial / row["path"]).read_bytes()
            if row["path"] == "scripts/eval_engine.py":
                payload += f"\n# isolated implementation fixture {suffix}\n".encode()
            path.write_bytes(payload)
            row["sha256"] = engine.file_sha256(path)
        write(self.preserve(directory / "snapshot_manifest.json"), manifest)
        index_path = self.root / "runs/campaign_1000/implementation/implementation_index.json"
        self.edit(index_path, lambda index: index["stages"]["development"].append({"scope": scope, "directory": directory.relative_to(self.root).as_posix()}))
        return engine.file_sha256(directory / "scripts/eval_engine.py")

    def test_checkpoint_interrupted_unknown_requests_are_counted_and_can_freeze(self):
        self.add_checkpoint_orphans()
        result = self.report()
        self.assertIn(result["state"], FROZEN, result.get("issues"))
        self.assertEqual(result["new_campaign_requests"], 911)
        self.assertEqual(result["development_requests"], 903)
        self.assertEqual(result["interruption_checkpoint"]["interrupted_reservation_count"], 3)
        for model in result["development"]:
            if model["output_name"] in {"deepseek-flash", "qwen3.8-flash", "glm-5.3-flash"}:
                self.assertEqual(model["attempted"], 150)
                self.assertEqual(model["requests"], 151)
                self.assertEqual(model["tokens"]["unknown_usage_requests"], 1)
                self.assertEqual(model["tokens"]["known_usage_requests"], 150)

    def test_checkpoint_must_bind_interrupted_request_item_model_and_stage(self):
        path, valid = self.add_checkpoint_orphans()
        for field, bad in (("item_id", "fixture-001"), ("model", "doubao-seed-2.1-lite"), ("stage", "precheck")):
            with self.subTest(field=field):
                changed = copy.deepcopy(valid)
                changed["pending"][0][field] = bad
                write(path, changed)
                self.assertNotFrozen(self.report())
        changed = copy.deepcopy(valid)
        changed["pending"].pop(0)
        write(path, changed)
        self.assertNotFrozen(self.report())

    def test_v3_snapshot_allows_new_run_start_and_existing_run_resume(self):
        version = self.add_implementation_snapshot("io_retry_v3", "io_retry_v3")
        self.edit(self.run_dir("doubao-seed-2.1-lite") / "run.json", lambda meta: meta.update(engine_sha256=version))
        self.edit(self.run_dir("deepseek-flash") / "run.json", lambda meta: meta.update(resume_implementations=[{"engine_sha256": version, "recorded_at": "2026-01-01T00:00:00+00:00"}]))
        result = self.report()
        self.assertIn(result["state"], FROZEN, result.get("issues"))
        models = {model["output_name"]: model for model in result["development"]}
        self.assertEqual(models["doubao-seed-2.1-lite"]["source_versions"]["original_engine_sha256"], version)
        self.assertIn(version, models["deepseek-flash"]["source_versions"]["resume_engine_sha256"])

    def test_v2_offline_candidate_cannot_be_real_run_start_or_resume_source(self):
        version = self.add_implementation_snapshot("io_retry_v2", "offline_candidate_v2")
        run_path = self.run_dir("doubao-seed-2.1-lite") / "run.json"
        original = engine.read_json(run_path)
        self.edit(run_path, lambda meta: meta.update(engine_sha256=version))
        self.assertNotFrozen(self.report())
        write(run_path, {**original, "resume_implementations": [{"engine_sha256": version}]})
        self.assertNotFrozen(self.report())


class PaddingEvidenceTests(unittest.TestCase):
    def test_unchanged_geometry_image_does_not_count_as_a_fifth_small_option(self):
        small = {"source_dimensions": [8, 35], "derived_dimensions": [32, 35], "source_sha256": "a" * 64, "derived_sha256": "b" * 64}
        main = {"source_dimensions": [157, 139], "derived_dimensions": [157, 139], "source_sha256": "c" * 64, "derived_sha256": "c" * 64}
        self.assertTrue(audit.padding_evidence_passes({"image_processing": [main, *[dict(small) for _ in range(4)]]}))
        self.assertFalse(audit.padding_evidence_passes({"image_processing": [main, *[dict(small) for _ in range(3)]]}))


if __name__ == "__main__":
    unittest.main()
