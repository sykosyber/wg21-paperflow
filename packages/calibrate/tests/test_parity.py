# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Replay parity: aggregate.py must reproduce what the real Lua printed.

The load-bearing test of the harness. Every recorded run's votes are fed to
the Python copy of the epilogue's arithmetic, with the constants that run was
made under, and every number the Lua printed must come back to the character:
the totals under all four rules, each criterion's grade under each rule, the
provisional line, the single-sample totals, the Weight line and its band span.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path

import pytest

from calibrate import aggregate, diagnostics, marking, shim, simulate

PARITY = Path(__file__).parent / "fixtures" / "synthetic" / "parity"
INDEX = [json.loads(line) for line in (PARITY / "index.jsonl").read_text(encoding="utf-8").splitlines()]


def two(x: float) -> str:
    return f"{x:.2f}"


def check_parity(report_text: str, diag_text: str, k: aggregate.EpilogueConstants) -> None:
    report = diagnostics.split_report(report_text)
    d = diagnostics.parse_diagnostics(diag_text)
    if not d.is_proposal:
        assert report.weight.line == "Weight: n/a"
        return
    a = aggregate.aggregate(d.shorts, d.vote_grid(), d.samples, k)
    assert d.inter_rule == k.inter_rule
    assert {r: two(a.shadow_points[r]) for r in aggregate.RULES} == d.totals
    assert two(a.points) == d.points == d.totals[k.inter_rule]
    assert d.grades == {s: two(g) for s, g in zip(a.shorts, a.scores)}
    for c, score, i in zip(d.criteria, a.scores, range(len(a.scores))):
        assert c.grade == two(score), c.short
        assert c.under_rule == {r: two(a.shadows[r][i]) for r in aggregate.RULES}, c.short
        assert (c.fired, c.strong) == (a.fired[i], a.strong[i]), c.short
        assert c.binary == (c.short in k.binary), c.short
        assert [v.mean for v in c.votes] == [two(aggregate.lua_mean(list(v.votes))) for v in c.votes]
    assert d.on_threshold == a.on_threshold
    assert d.met == a.met
    assert d.single_sample_totals == tuple(two(t) for t in a.sample_totals)
    assert d.provisional_line == a.provisional_line
    assert report.weight.line == a.weight_line
    assert report.weight.span == a.span
    assert report.weight.shown == aggregate.lua_round(a.points)


def test_there_are_enough_fixtures() -> None:
    assert len(INDEX) >= 40
    assert {row["constants"]["INTER_RULE"] for row in INDEX} == set(aggregate.RULES)
    assert {row["edge"] for row in INDEX} >= {
        "h2 fallback", "not a proposal", "all-zero votes", "single section"}
    assert len({row["profile"] for row in INDEX}) >= 4
    assert len({row["paper"] for row in INDEX}) >= 10
    assert all(row["synthetic"] is True for row in INDEX)


@pytest.mark.parametrize("row", INDEX, ids=[row["name"] for row in INDEX])
def test_parity_on_recorded_run(row: dict) -> None:
    report_text = (PARITY / f"{row['name']}.report.md").read_text(encoding="utf-8")
    diag_text = (PARITY / f"{row['name']}.diagnostics.md").read_text(encoding="utf-8")
    assert marking.is_synthetic_text(report_text) and marking.is_synthetic_text(diag_text)
    check_parity(report_text, diag_text, aggregate.EpilogueConstants.from_dict(row["constants"]))


def test_edge_fixtures_show_their_edge() -> None:
    by_edge = {row["edge"]: row for row in INDEX if row["edge"]}

    def diag(edge: str) -> diagnostics.Diagnostics:
        return diagnostics.parse_diagnostics(
            (PARITY / f"{by_edge[edge]['name']}.diagnostics.md").read_text(encoding="utf-8"))

    assert diag("h2 fallback").headings.startswith("h3 ")
    assert not diag("not a proposal").is_proposal
    assert diag("all-zero votes").totals == dict.fromkeys(aggregate.RULES, "0.00")
    assert diag("single section").sections == 1
    rejected = [row for row in INDEX if row["invalid_quote_rate"] > 0]
    missing = [row for row in INDEX if row["missing_rate"] > 0]
    assert rejected and diag_of(rejected[0]).rejected > 0
    assert missing and diag_of(missing[0]).missing > 0


def diag_of(row: dict) -> diagnostics.Diagnostics:
    return diagnostics.parse_diagnostics(
        (PARITY / f"{row['name']}.diagnostics.md").read_text(encoding="utf-8"))


@pytest.mark.parametrize("rule", aggregate.RULES)
@pytest.mark.parametrize(("stem", "pid"), [("p1122r3", "P1122R3"), ("p3290r4", "P3290R4")])
def test_parity_on_the_current_prompt(prompt_text: str, ideal_paper, rule: str, stem: str, pid: str) -> None:
    """Live, so a change to the current epilogue that aggregate.py misses fails here too."""
    prompt = aggregate.patch_constants(prompt_text, INTER_RULE=rule)
    grader = simulate.SimulatedGrader(simulate.PROFILES["noisy"], truth_seed=9, noise_seed=10)
    run = shim.run_paper(prompt, ideal_paper(stem), grader, paper_id=pid)
    check_parity(run.report, run.diagnostics, aggregate.EpilogueConstants.from_prompt(prompt))


def test_patch_constants_touches_only_the_constants(prompt_text: str) -> None:
    patched = aggregate.patch_constants(
        prompt_text, INTER_RULE="max", STRONG=1.25, BINARY=[],
        LABELS=[(0, "Weightless"), (2, "Light"), (14, "Heavy")])
    k = aggregate.EpilogueConstants.from_prompt(patched)
    assert (k.inter_rule, k.strong, k.binary) == ("max", 1.25, frozenset())
    assert k.labels == ((0, "Weightless"), (2, "Light"), (14, "Heavy"))
    ref = shim.parse_prompt(prompt_text).assess_epilogue.code
    cand = shim.parse_prompt(patched).assess_epilogue.code
    assert aggregate.unmodelled_changes(ref, cand) == []
    # Nothing outside the Assess epilogue moved.
    block = shim.parse_prompt(prompt_text).assess_epilogue
    matcher = difflib.SequenceMatcher(a=prompt_text.split("\n"), b=patched.split("\n"), autojunk=False)
    changed = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    assert changed
    for _, i1, i2, _, _ in changed:
        assert block.first_line - 1 <= i1 and i2 <= block.last_line


def test_the_current_prompt_patches_round_trip(prompt_text: str) -> None:
    k = aggregate.EpilogueConstants.from_prompt(prompt_text)
    assert k.inter_rule == "top2"
    same = aggregate.patch_constants(prompt_text, **{
        "INTER_RULE": k.inter_rule, "LABELS": list(k.labels), "BINARY": sorted(k.binary)})
    assert same == prompt_text


def test_unmodelled_epilogue_changes_are_listed(prompt_text: str) -> None:
    code = shim.parse_prompt(prompt_text).assess_epilogue.code
    changed = code.replace("local QUOTE_WORDS = 40", "local QUOTE_WORDS = 30")
    assert aggregate.unmodelled_changes(code, changed) == [
        "-local QUOTE_WORDS = 40", "+local QUOTE_WORDS = 30"]
