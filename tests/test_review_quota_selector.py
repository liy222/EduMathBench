"""Exact marginal quotas, fixed protection and deterministic preference checks."""
from __future__ import annotations

import copy
import itertools
import json
import random
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from review_quota_selector import QuotaSelectionError, select_public


def question(identifier, module="X", difficulty="easy", grade=7):
    return {"id": identifier, "grade": grade, "module": module, "difficulty": difficulty,
            "question": "original content", "options": {"A": "a", "B": "b", "C": "c", "D": "d"}}


class QuotaSelectorTests(unittest.TestCase):
    def assert_margins(self, selected, cells, difficulties):
        self.assertEqual(Counter((q["grade"], q["module"]) for q in selected), Counter({k: v for k, v in cells.items() if v}))
        self.assertEqual(Counter(q["difficulty"] for q in selected), Counter({k: v for k, v in difficulties.items() if v}))

    def test_joint_quotas_choose_required_cached_replacement(self):
        candidates = [question("reviewed-x"), question("reviewed-y", "Y"), question("cached-y", "Y", "hard")]
        cells, difficulties = {(7, "X"): 1, (7, "Y"): 1}, {"easy": 1, "hard": 1}
        selected, report = select_public(candidates, {"reviewed-x"}, cells, difficulties,
                                         {"reviewed-x", "reviewed-y"})
        self.assert_margins(selected, cells, difficulties)
        self.assertEqual({q["id"] for q in selected}, {"reviewed-x", "cached-y"})
        self.assertEqual(report["selected_new_ids"], ["cached-y"])
        self.assertEqual(report["excluded_preferred_ids"], ["reviewed-y"])
        self.assertIn("exact_joint_quotas", report["replacements"]["added"][0]["reason"])
        json.dumps(report, ensure_ascii=False)

    def test_preference_is_global_and_strictly_beats_tie_costs(self):
        candidates = [question(f"x-e-{i}") for i in range(5)] + [question(f"x-h-{i}", difficulty="hard") for i in range(5)]
        candidates += [question(f"y-e-{i}", "Y") for i in range(5)] + [question(f"y-h-{i}", "Y", "hard") for i in range(5)]
        cells, difficulties = {(7, "X"): 3, (7, "Y"): 3}, {"easy": 3, "hard": 3}
        preferred = {"x-e-1", "x-e-2", "x-e-3", "y-h-1", "y-h-2", "y-h-3"}
        selected, report = select_public(candidates, [], cells, difficulties, preferred)
        self.assertEqual({q["id"] for q in selected}, preferred)
        self.assertEqual(report["new_selected_count"], 0)

    def test_small_instance_matches_exhaustive_minimum_additions(self):
        candidates = [question("xe"), question("xh", difficulty="hard"), question("ye", "Y"),
                      question("yh", "Y", "hard"), question("ye2", "Y"), question("xh2", difficulty="hard")]
        cells, difficulties = {(7, "X"): 2, (7, "Y"): 1}, {"easy": 2, "hard": 1}
        preferred, mandatory = {"xe", "yh", "ye"}, {"xh"}
        feasible = []
        for subset in itertools.combinations(candidates, 3):
            if not mandatory <= {q["id"] for q in subset}:
                continue
            if Counter((q["grade"], q["module"]) for q in subset) == Counter(cells) and Counter(q["difficulty"] for q in subset) == Counter(difficulties):
                feasible.append(sum(q["id"] not in preferred for q in subset))
        selected, report = select_public(candidates, mandatory, cells, difficulties, preferred)
        self.assertEqual(sum(q["id"] not in preferred for q in selected), min(feasible))
        self.assertIn("xh", {q["id"] for q in selected})
        self.assertEqual(report["mandatory_count"], 1)

    def test_selection_and_report_are_independent_of_input_order(self):
        candidates = [question(str(i), "X" if i % 2 else "Y", "easy" if i % 3 else "hard") for i in range(30)]
        cells, difficulties = {(7, "X"): 5, (7, "Y"): 5}, {"easy": 6, "hard": 4}
        baseline = select_public(candidates, ["3"], cells, difficulties, {str(i) for i in range(15)}, seed="stable")
        shuffled = list(candidates)
        random.Random(18).shuffle(shuffled)
        repeated = select_public(shuffled, ["3"], dict(reversed(list(cells.items()))),
                                 dict(reversed(list(difficulties.items()))), {str(i) for i in reversed(range(15))}, seed="stable")
        self.assertEqual(baseline, repeated)

    def test_fixed_overfull_reports_both_margins(self):
        candidates = [question("a"), question("b"), question("c", "Y", "hard")]
        with self.assertRaises(QuotaSelectionError) as caught:
            select_public(candidates, {"a", "b"}, {(7, "X"): 1, (7, "Y"): 1}, {"easy": 1, "hard": 1})
        deficit = caught.exception.deficit
        self.assertEqual(deficit["reason"], "fixed_overfull")
        self.assertEqual(deficit["cells"][0]["excess"], 1)
        self.assertEqual(deficit["difficulties"][0]["excess"], 1)

    def test_basic_supply_shortage_returns_structured_deficit(self):
        with self.assertRaises(QuotaSelectionError) as caught:
            select_public([question("only")], [], {(7, "X"): 2}, {"easy": 2})
        deficit = caught.exception.deficit
        self.assertEqual(deficit["reason"], "insufficient_supply")
        self.assertEqual(deficit["shortfall"], 1)
        self.assertEqual(deficit["cells"][0]["eligible_optional"], 1)
        self.assertEqual(deficit["difficulties"][0]["deficit"], 1)

    def test_joint_bottleneck_is_detected_when_each_margin_has_enough_supply(self):
        # X and Y can only supply easy; Z supplies both hard items. All individual
        # cell and difficulty supply counts meet their targets, yet the cut fails.
        candidates = [question("xe"), question("ye", "Y"), question("zh1", "Z", "hard"), question("zh2", "Z", "hard")]
        with self.assertRaises(QuotaSelectionError) as caught:
            select_public(candidates, [], {(7, "X"): 1, (7, "Y"): 1, (7, "Z"): 1}, {"easy": 1, "hard": 2})
        deficit = caught.exception.deficit
        self.assertEqual(deficit["reason"], "insufficient_supply")
        self.assertEqual(deficit["available_flow"], 2)
        self.assertTrue(all(item["eligible_optional"] >= item["remaining"] for item in deficit["cells"]))
        self.assertTrue(all(item["eligible_optional"] >= item["remaining"] for item in deficit["difficulties"]))
        self.assertTrue(deficit["bottleneck"]["reachable_cells"])

    def test_duplicate_candidate_ids_are_rejected(self):
        with self.assertRaises(QuotaSelectionError) as caught:
            select_public([question("same"), question("same", difficulty="hard")], [], {(7, "X"): 1}, {"easy": 1})
        self.assertEqual(caught.exception.deficit, {"reason": "duplicate_candidate_ids", "ids": ["same"]})

    def test_missing_mandatory_is_never_silently_dropped(self):
        with self.assertRaises(QuotaSelectionError) as caught:
            select_public([question("a")], {"absent"}, {(7, "X"): 1}, {"easy": 1})
        self.assertEqual(caught.exception.deficit["reason"], "missing_mandatory_candidates")

    def test_mandatory_outside_quota_labels_is_rejected(self):
        with self.assertRaises(QuotaSelectionError) as caught:
            select_public([question("a", difficulty="other")], {"a"}, {(7, "X"): 1}, {"easy": 1})
        self.assertEqual(caught.exception.deficit["reason"], "mandatory_outside_targets")

    def test_unsupported_labels_are_excluded_without_relabeling(self):
        candidates = [question("a"), question("unsupported", difficulty="other"), question("outside", "Z")]
        original = copy.deepcopy(candidates)
        selected, report = select_public(candidates, [], {(7, "X"): 1}, {"easy": 1}, {"a", "unsupported", "outside"})
        self.assertEqual([q["id"] for q in selected], ["a"])
        self.assertEqual(set(report["ineligible_candidate_ids"]), {"unsupported", "outside"})
        self.assertEqual(candidates, original)
        selected[0]["options"]["A"] = "changed"
        self.assertEqual(candidates, original)

    def test_config_cell_records_and_zero_targets_are_supported(self):
        selected, _report = select_public([question("a")], [], [{"grade": 7, "module": "X", "target": 1},
                                                                 {"grade": 7, "module": "Y", "target": 0}], {"easy": 1, "hard": 0})
        self.assertEqual([q["id"] for q in selected], ["a"])

    def test_target_totals_and_invalid_counts_fail_clearly(self):
        for cells, difficulties, reason in [({(7, "X"): 2}, {"easy": 1}, "target_total_mismatch"),
                                             ({(7, "X"): -1}, {"easy": -1}, "invalid_targets")]:
            with self.subTest(reason=reason), self.assertRaises(QuotaSelectionError) as caught:
                select_public([], [], cells, difficulties)
            self.assertEqual(caught.exception.deficit["reason"], reason)

    def test_zero_target_returns_no_selection(self):
        selected, report = select_public([question("a")], [], {(7, "X"): 0}, {"easy": 0})
        self.assertEqual(selected, [])
        self.assertEqual(report["selected_count"], 0)

    def test_real_quota_scale_has_exact_1500_and_600_600_300_margins(self):
        config = json.loads((ROOT / "config/quotas.json").read_text(encoding="utf-8"))
        rows, target_difficulties = [], []
        for difficulty, count in config["difficulty_targets"].items():
            target_difficulties.extend([difficulty] * count)
        for cell in config["cells"]:
            for _ in range(cell["target"]):
                index = len(rows)
                rows.append(question(f"q{index}", cell["module"], target_difficulties[index], cell["grade"]))
        # Surplus supply exercises preference without depending on live data.
        surplus = [dict(q, id="spare-" + q["id"]) for q in rows[::5]]
        selected, report = select_public(rows + surplus, {q["id"] for q in rows[:50]}, config["cells"],
                                         config["difficulty_targets"], {q["id"] for q in rows})
        cells = {(cell["grade"], cell["module"]): cell["target"] for cell in config["cells"]}
        self.assert_margins(selected, cells, config["difficulty_targets"])
        self.assertEqual(len(selected), 1500)
        self.assertEqual(report["new_selected_count"], 0)


if __name__ == "__main__":
    unittest.main()
