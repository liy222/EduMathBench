"""Read live local progress without contacting models or reading credentials."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import time

import eval_engine as engine
import run_development_campaign as campaign


def status() -> dict:
    definition = engine.read_json(campaign.CAMPAIGN)
    accounting = campaign.request_accounting(definition)
    meta_path = campaign.OUT / "campaign.json"
    state = engine.read_json(meta_path).get("state") if meta_path.exists() else "not_started"
    result = {"state": state, "accounting": accounting, "stages": []}
    for stage in definition["stages"]:
        manifest = engine.read_json(campaign.ROOT / stage["manifest"])
        summary_path = campaign.ROOT / stage["output"] / "batch_summary.json"
        batch_summary = engine.read_json(summary_path) if summary_path.exists() else {}
        workers = {row["output_name"]: row for row in batch_summary.get("models", [])}
        models = []
        for row in manifest["models"]:
            folder = campaign.ROOT / stage["output"] / row["output_name"]
            journal = folder / "predictions.jsonl"
            records = engine.read_jsonl(journal) if journal.exists() else []
            model_meta = engine.read_json(folder / "run.json") if (folder / "run.json").exists() else {}
            models.append({
                "model": model_meta.get("config", {}).get("backend", {}).get("model", row["output_name"]),
                "state": model_meta.get("state", "not_started"),
                "worker_state": workers.get(row["output_name"], {}).get("state", "not_started"),
                "worker_error": workers.get(row["output_name"], {}).get("error_type"),
                "committed_items": len(records),
                "attempted_items": sum(bool(r.get("attempted")) for r in records),
                "parsed_answers": sum(r.get("status") == "ok" for r in records),
                "status_counts": dict(Counter(r.get("status") for r in records)),
                "requests": len(model_meta.get("remote_attempts", [])),
            })
        result["stages"].append({"name": stage["name"], "models": models})
    engine.write_json(campaign.OUT / "status.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.interval <= 60:
        parser.error("interval must be between 1 and 60 seconds")
    while True:
        progress = status()
        print(json.dumps(progress, ensure_ascii=False), flush=True)
        if not args.watch or progress["state"] != "running":
            break
        time.sleep(args.interval)
