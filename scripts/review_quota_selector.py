"""Deterministic public-question selection with two exact quota margins.

Input eligibility and provenance are the caller's responsibility. This module
never changes grade, module, difficulty, or question content. Mandatory questions
are fixed first; a minimum-cost flow fills the remaining cell/difficulty quotas.
"""
from __future__ import annotations

import copy
import hashlib
import heapq
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_SEED = "EduMathBench-review-v0.3"
Cell = tuple[int, str]


class QuotaSelectionError(ValueError):
    """Invalid or unsatisfiable selection, with a JSON-serializable deficit."""

    def __init__(self, deficit: Mapping[str, Any]):
        self.deficit = copy.deepcopy(dict(deficit))
        super().__init__(json.dumps(self.deficit, ensure_ascii=False, sort_keys=True))


def _fail(reason: str, **details: Any) -> None:
    raise QuotaSelectionError({"reason": reason, **details})


def _count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("invalid_targets", field=label, value=repr(value), detail="target must be a nonnegative integer")
    return value


def _cell(grade: Any, module: Any) -> Cell:
    if isinstance(grade, bool) or not isinstance(grade, int) or not isinstance(module, str) or not module:
        _fail("invalid_targets", grade=repr(grade), module=repr(module), detail="cell requires integer grade and nonempty module")
    return grade, module


def _targets(cell_targets: Any, difficulty_targets: Mapping[str, int]) -> tuple[dict[Cell, int], dict[str, int]]:
    cells: dict[Cell, int] = {}
    if isinstance(cell_targets, Mapping):
        entries = []
        for key, value in cell_targets.items():
            if not isinstance(key, tuple) or len(key) != 2:
                _fail("invalid_targets", field="cell_targets", detail="mapping keys must be (grade, module) tuples")
            entries.append((key[0], key[1], value))
    elif isinstance(cell_targets, Sequence) and not isinstance(cell_targets, (str, bytes)):
        entries = []
        for entry in cell_targets:
            if not isinstance(entry, Mapping) or not {"grade", "module", "target"} <= set(entry):
                _fail("invalid_targets", field="cell_targets", detail="cell records require grade, module, target")
            entries.append((entry["grade"], entry["module"], entry["target"]))
    else:
        _fail("invalid_targets", field="cell_targets", detail="expected cell mapping or config cells list")
    for grade, module, target in entries:
        key = _cell(grade, module)
        if key in cells:
            _fail("invalid_targets", field="cell_targets", detail="duplicate cell", grade=grade, module=module)
        cells[key] = _count(target, f"cell {key}")
    if not isinstance(difficulty_targets, Mapping):
        _fail("invalid_targets", field="difficulty_targets", detail="expected difficulty mapping")
    difficulties: dict[str, int] = {}
    for difficulty, target in difficulty_targets.items():
        if not isinstance(difficulty, str) or not difficulty:
            _fail("invalid_targets", field="difficulty_targets", detail="difficulty labels must be nonempty strings")
        difficulties[difficulty] = _count(target, difficulty)
    if sum(cells.values()) != sum(difficulties.values()):
        _fail("target_total_mismatch", cell_total=sum(cells.values()), difficulty_total=sum(difficulties.values()))
    return dict(sorted(cells.items())), dict(sorted(difficulties.items()))


def _ids(values: Iterable[str], name: str) -> set[str]:
    if isinstance(values, (str, bytes)):
        _fail("invalid_ids", field=name, detail="expected an iterable of question IDs")
    try:
        result = set(values)
    except (TypeError, ValueError):
        _fail("invalid_ids", field=name, detail="question IDs must be nonempty strings")
    if any(not isinstance(value, str) or not value for value in result):
        _fail("invalid_ids", field=name, detail="question IDs must be nonempty strings")
    return result


@dataclass
class _Edge:
    to: int
    reverse: int
    capacity: int
    cost: int


class _MinCostFlow:
    def __init__(self, size: int):
        self.graph: list[list[_Edge]] = [[] for _ in range(size)]

    def edge(self, source: int, target: int, capacity: int, cost: int = 0) -> _Edge:
        forward = _Edge(target, len(self.graph[target]), capacity, cost)
        reverse = _Edge(source, len(self.graph[source]), 0, -cost)
        self.graph[source].append(forward)
        self.graph[target].append(reverse)
        return forward

    def run(self, source: int, sink: int, requested: int) -> tuple[int, int]:
        flow = total_cost = 0
        potentials = [0] * len(self.graph)
        while flow < requested:
            distances: list[int | None] = [None] * len(self.graph)
            previous: list[tuple[int, int] | None] = [None] * len(self.graph)
            distances[source] = 0
            queue = [(0, source)]
            while queue:
                distance, node = heapq.heappop(queue)
                if distance != distances[node]:
                    continue
                for index, edge in enumerate(self.graph[node]):
                    if edge.capacity <= 0:
                        continue
                    candidate = distance + edge.cost + potentials[node] - potentials[edge.to]
                    if distances[edge.to] is None or candidate < distances[edge.to]:
                        distances[edge.to] = candidate
                        previous[edge.to] = (node, index)
                        heapq.heappush(queue, (candidate, edge.to))
            if distances[sink] is None:
                break
            for node, distance in enumerate(distances):
                if distance is not None:
                    potentials[node] += distance
            amount = requested - flow
            node = sink
            while node != source:
                prior, index = previous[node]  # type: ignore[misc]
                amount = min(amount, self.graph[prior][index].capacity)
                node = prior
            node = sink
            while node != source:
                prior, index = previous[node]  # type: ignore[misc]
                edge = self.graph[prior][index]
                edge.capacity -= amount
                self.graph[node][edge.reverse].capacity += amount
                total_cost += amount * edge.cost
                node = prior
            flow += amount
        return flow, total_cost

    def reachable(self, source: int) -> set[int]:
        reached = {source}
        pending = [source]
        while pending:
            node = pending.pop()
            for edge in self.graph[node]:
                if edge.capacity > 0 and edge.to not in reached:
                    reached.add(edge.to)
                    pending.append(edge.to)
        return reached


def select_public(candidates: Iterable[Mapping[str, Any]], mandatory_ids: Iterable[str],
                  cell_targets: Any, difficulty_targets: Mapping[str, int],
                  preferred_ids: Iterable[str] | None = None,
                  seed: str = DEFAULT_SEED) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select exact quotas, retaining the greatest number of preferred IDs.

    ``cell_targets`` accepts ``config['cells']`` or ``{(grade, module): count}``.
    Mandatory IDs must exist and fit both quota margins. Duplicate candidate IDs
    are rejected. With ``preferred_ids=None`` all candidates are equally preferred.
    Otherwise every nonpreferred optional item has a cost greater than the total
    possible tie costs, making the minimum number of additions the first priority.
    Ties and returned order use SHA-256(seed + NUL + id), independent of input order.

    Returns deep copies and a JSON-serializable selection/replacement report.
    Infeasible constraints raise ``QuotaSelectionError`` with ``.deficit``;
    no relabeling or partial selection is returned.
    """
    cells, difficulties = _targets(cell_targets, difficulty_targets)
    if not isinstance(seed, str):
        _fail("invalid_seed", detail="seed must be text")
    mandatory = _ids(mandatory_ids, "mandatory_ids")
    by_id: dict[str, Mapping[str, Any]] = {}
    duplicates = set()
    invalid = []
    for index, question in enumerate(candidates):
        if not isinstance(question, Mapping):
            invalid.append({"index": index, "detail": "candidate must be an object"})
            continue
        identifier = question.get("id")
        if not isinstance(identifier, str) or not identifier:
            invalid.append({"index": index, "detail": "candidate requires a nonempty string id"})
            continue
        grade, module, difficulty = (question.get(field) for field in ("grade", "module", "difficulty"))
        if (isinstance(grade, bool) or not isinstance(grade, int) or not isinstance(module, str)
                or not module or not isinstance(difficulty, str) or not difficulty):
            invalid.append({"id": identifier, "detail": "candidate requires integer grade and nonempty module/difficulty"})
        if identifier in by_id:
            duplicates.add(identifier)
        by_id[identifier] = question
    if invalid:
        _fail("invalid_candidates", issues=invalid)
    if duplicates:
        _fail("duplicate_candidate_ids", ids=sorted(duplicates))
    missing = mandatory - by_id.keys()
    if missing:
        _fail("missing_mandatory_candidates", ids=sorted(missing))
    preferred = set(by_id) if preferred_ids is None else _ids(preferred_ids, "preferred_ids")

    def rank(identifier: str) -> tuple[str, str]:
        return hashlib.sha256((seed + "\0" + identifier).encode("utf-8")).hexdigest(), identifier

    def ordered(identifiers: Iterable[str]) -> list[str]:
        return sorted(identifiers, key=rank)

    def cell_of(identifier: str) -> Cell:
        question = by_id[identifier]
        return question["grade"], question["module"]

    outside = [identifier for identifier in ordered(mandatory)
               if cell_of(identifier) not in cells or by_id[identifier]["difficulty"] not in difficulties]
    if outside:
        _fail("mandatory_outside_targets", ids=outside)
    fixed_cells = Counter(cell_of(identifier) for identifier in mandatory)
    fixed_difficulties = Counter(by_id[identifier]["difficulty"] for identifier in mandatory)
    over_cells = [{"grade": grade, "module": module, "target": target, "mandatory": fixed_cells[(grade, module)],
                   "excess": fixed_cells[(grade, module)] - target}
                  for (grade, module), target in cells.items() if fixed_cells[(grade, module)] > target]
    over_difficulties = [{"difficulty": difficulty, "target": target, "mandatory": fixed_difficulties[difficulty],
                          "excess": fixed_difficulties[difficulty] - target}
                         for difficulty, target in difficulties.items() if fixed_difficulties[difficulty] > target]
    if over_cells or over_difficulties:
        _fail("fixed_overfull", cells=over_cells, difficulties=over_difficulties)

    eligible = {identifier for identifier in by_id
                if cell_of(identifier) in cells and by_id[identifier]["difficulty"] in difficulties}
    optional = ordered(eligible - mandatory)
    remaining_cells = {cell: target - fixed_cells[cell] for cell, target in cells.items()}
    remaining_difficulties = {difficulty: target - fixed_difficulties[difficulty]
                              for difficulty, target in difficulties.items()}
    required = sum(remaining_cells.values())
    cell_nodes = {cell: index + 1 for index, cell in enumerate(cells)}
    difficulty_nodes = {difficulty: len(cells) + index + 1 for index, difficulty in enumerate(difficulties)}
    source, sink = 0, len(cells) + len(difficulties) + 1
    network = _MinCostFlow(sink + 1)
    cell_edges = {cell: network.edge(source, cell_nodes[cell], target) for cell, target in remaining_cells.items()}
    difficulty_edges = {difficulty: network.edge(difficulty_nodes[difficulty], sink, target)
                        for difficulty, target in remaining_difficulties.items()}
    # One fewer new question outweighs every possible change in rank-sum.
    addition_cost = required * (len(optional) + 1) + 1
    question_edges = {}
    for tie, identifier in enumerate(optional):
        cost = tie + (0 if identifier in preferred else addition_cost)
        question_edges[identifier] = network.edge(
            cell_nodes[cell_of(identifier)], difficulty_nodes[by_id[identifier]["difficulty"]], 1, cost
        )
    flow, total_cost = network.run(source, sink, required)
    if flow != required:
        supply_cells = Counter(cell_of(identifier) for identifier in optional)
        supply_difficulties = Counter(by_id[identifier]["difficulty"] for identifier in optional)
        reachable = network.reachable(source)
        _fail("insufficient_supply", required_optional=required, available_flow=flow, shortfall=required - flow,
              cells=[{"grade": grade, "module": module, "target": cells[(grade, module)],
                      "mandatory": fixed_cells[(grade, module)], "remaining": target,
                      "eligible_optional": supply_cells[(grade, module)],
                      "filled": target - cell_edges[(grade, module)].capacity,
                      "deficit": cell_edges[(grade, module)].capacity}
                     for (grade, module), target in remaining_cells.items()],
              difficulties=[{"difficulty": difficulty, "target": difficulties[difficulty],
                             "mandatory": fixed_difficulties[difficulty], "remaining": target,
                             "eligible_optional": supply_difficulties[difficulty],
                             "filled": target - difficulty_edges[difficulty].capacity,
                             "deficit": difficulty_edges[difficulty].capacity}
                            for difficulty, target in remaining_difficulties.items()],
              bottleneck={"reachable_cells": [{"grade": grade, "module": module}
                                               for (grade, module), node in cell_nodes.items() if node in reachable],
                          "reachable_difficulties": [difficulty for difficulty, node in difficulty_nodes.items()
                                                     if node in reachable]})

    selected_ids = mandatory | {identifier for identifier, edge in question_edges.items() if edge.capacity == 0}
    ordered_selected = ordered(selected_ids)
    selected_cells = Counter(cell_of(identifier) for identifier in selected_ids)
    selected_difficulties = Counter(by_id[identifier]["difficulty"] for identifier in selected_ids)
    if selected_cells != Counter({cell: count for cell, count in cells.items() if count}) or selected_difficulties != Counter({d: n for d, n in difficulties.items() if n}):
        raise RuntimeError("Internal error: selected margins differ from target quotas")

    def describe(identifier: str, reason: str) -> dict[str, Any]:
        question = by_id[identifier]
        return {"id": identifier, "grade": question["grade"], "module": question["module"],
                "difficulty": question["difficulty"], "reason": reason}

    additions = [describe(identifier, "cached_candidate_needed_for_exact_joint_quotas")
                 for identifier in ordered_selected if identifier not in preferred]
    removed = [describe(identifier, "preferred_question_excluded_to_satisfy_exact_joint_quotas")
               for identifier in ordered(preferred & by_id.keys() - selected_ids)]
    report = {
        "seed": seed, "selected_count": len(selected_ids), "mandatory_count": len(mandatory),
        "preferred_available_count": len(preferred & by_id.keys()),
        "preferred_selected_count": len(preferred & selected_ids), "new_selected_count": len(selected_ids - preferred),
        "optional_selected_count": flow,
        "mandatory_ids": ordered(mandatory), "selected_ids": ordered_selected,
        "unavailable_preferred_ids": ordered(preferred - by_id.keys()),
        "excluded_preferred_ids": [item["id"] for item in removed],
        "selected_new_ids": [item["id"] for item in additions],
        "selection_reasons": [describe(identifier, "mandatory_protection" if identifier in mandatory else
                                         "preferred_reviewed_question" if identifier in preferred else
                                         "cached_candidate_needed_for_exact_joint_quotas")
                              for identifier in ordered_selected],
        "replacements": {"added": additions, "removed": removed},
        "ineligible_candidate_ids": ordered(set(by_id) - eligible),
        "cells": [{"grade": grade, "module": module, "target": target,
                   "selected": selected_cells[(grade, module)], "mandatory": fixed_cells[(grade, module)]}
                  for (grade, module), target in cells.items()],
        "difficulties": {difficulty: {"target": target, "selected": selected_difficulties[difficulty],
                                      "mandatory": fixed_difficulties[difficulty]}
                         for difficulty, target in difficulties.items()},
        "objective": {"new_optional_count": len((selected_ids - mandatory) - preferred),
                      "addition_unit_cost": addition_cost, "minimum_cost": total_cost},
    }
    return [copy.deepcopy(dict(by_id[identifier])) for identifier in ordered_selected], report
