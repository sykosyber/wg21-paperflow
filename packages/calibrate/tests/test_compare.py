# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Gates, readings, band changes and the comment."""

from __future__ import annotations

import dataclasses
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from calibrate import aggregate, compare, golden, metrics, replay, run, score, simulate

FIXED = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
PAPERS = ("P0533R9", "P0957R8", "P1068R11", "P3556R0", "P3953R0", "P4228R0")


def clock() -> datetime:
    return FIXED


@pytest.fixture(scope="module")
def cset(package_root: Path, prompt_text: str) -> golden.CalibrationSet:
    return golden.load_for_prompt(package_root / "data" / "synthetic", prompt_text)


def shim_run(tmp_path: Path, prompt: str, cset, name: str, profile="noisy", papers=PAPERS) -> Path:
    path = tmp_path / f"{name}.md"
    path.write_bytes(prompt.encode("utf-8"))
    prof = simulate.PROFILES[profile] if isinstance(profile, str) else profile
    backend = run.ShimBackend(prompt_text=prompt, profile=prof, seed=5)
    config = run.RunConfig(prompt_path=path, repeats=2, jobs=3, papers=papers, out=tmp_path / name)
    return run.full_run(config, backend, cset, now=clock)


@pytest.fixture(scope="module")
def baseline(tmp_path_factory, prompt_text: str, cset) -> run.RunFolder:
    return run.load_run(shim_run(tmp_path_factory.mktemp("base"), prompt_text, cset, "base"))


# --- readings ----------------------------------------------------------------------------


def iv(low: float, high: float) -> metrics.Interval:
    return metrics.Interval(estimate=(low + high) / 2, low=low, high=high, used=2000, dropped=0)


@pytest.mark.parametrize(("low", "high", "improving", "expected"), [
    (-0.9, -0.2, -1, compare.BETTER), (0.1, 0.5, -1, compare.WORSE), (-0.3, 0.4, -1, compare.WITHIN_NOISE),
    (0.1, 0.5, +1, compare.BETTER), (-0.9, -0.2, +1, compare.WORSE), (0.0, 0.4, +1, compare.WITHIN_NOISE),
])
def test_reading_for(low: float, high: float, improving: int, expected: str) -> None:
    assert compare.reading_for(iv(low, high), improving) == expected


def test_reading_for_an_undefined_interval() -> None:
    assert compare.reading_for(metrics.Interval(None, None, None, 0, 2000), -1) == compare.NO_READING


@pytest.mark.parametrize(("line", "ok"), [
    ("Weight: Medium (6/14)", True), ("Weight: Light to Heavy (7/14)", True), ("Weight: n/a", True),
    ("Weight: Hefty (6/14)", False), ("Weight: Medium", False), ("Weight: Medium to (6/14)", False),
])
def test_weight_line_format(prompt_text: str, line: str, ok: bool) -> None:
    labels = aggregate.EpilogueConstants.from_prompt(prompt_text).labels
    assert bool(compare.weight_line_re(labels).match(line)) is ok


# --- gates -----------------------------------------------------------------------------


def test_a_clean_run_passes_every_gate(baseline, cset) -> None:
    gates = compare.gates(baseline, cset)
    assert [g.passed for g in gates] == [True] * 4, gates


def test_a_failed_run_fails_gate_1(tmp_path: Path, baseline, cset) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(baseline.path, copy)
    result = copy / "P0533R9.r1" / "result.json"
    data = json.loads(result.read_text(encoding="utf-8"))
    data.update(status="failed", exit_code=1, error="exited 1")
    result.write_text(json.dumps(data), encoding="utf-8")
    gates = compare.gates(run.load_run(copy), cset)
    assert not gates[0].passed and "P0533R9.r1 (exited 1)" in gates[0].detail
    assert gates[1].passed and gates[3].passed


def test_missing_replies_fail_gate_2(tmp_path: Path, prompt_text: str, cset) -> None:
    dropping = dataclasses.replace(simulate.PROFILES["calibrated"], missing_rate=0.05)
    folder = run.load_run(shim_run(tmp_path, prompt_text, cset, "m", profile=dropping, papers=("P0533R9",)))
    gates = compare.gates(folder, cset)
    assert not gates[1].passed and "P0533R9.r1" in gates[1].detail
    assert gates[0].passed


def test_a_renamed_criterion_fails_gate_3(tmp_path: Path, prompt_text: str, cset) -> None:
    renamed = prompt_text.replace('short = "prior_art"', 'short = "alternatives"', 1)
    folder = run.load_run(shim_run(tmp_path, renamed, cset, "r", papers=("P3953R0",)))
    cmp = compare.compare(folder, None, cset)
    g3 = cmp.gates[2]
    assert not g3.passed
    assert "graded but not in CRITERIA: ['prior_art']" in g3.detail
    assert "in CRITERIA but not graded: ['alternatives']" in g3.detail
    assert cmp.candidate is None and "No readings" in compare.render_comment(cmp)


def test_broken_parity_fails_gate_4_for_the_run_and_its_replays(tmp_path: Path, baseline,
                                                                 prompt_text: str, cset) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(baseline.path, copy)
    diag = copy / "P0957R8.r2" / "diagnostics.md"
    text = diag.read_text(encoding="utf-8")
    line = next(x for x in text.split("\n") if x.startswith("Totals under every inter-section rule:"))
    diag.write_text(text.replace(line, line.replace("max ", "max 1", 1)), encoding="utf-8")
    gates = compare.gates(run.load_run(copy), cset)
    assert not gates[3].passed and gates[3].detail.startswith("P0957R8.r2: total under max")
    # A replay of a run that fails parity is refused outright.
    with pytest.raises(replay.ReplayError, match="parity fails"):
        replay.replay_run(run.load_run(copy), prompt_text, tmp_path / "r", now=clock)


# --- comparisons -------------------------------------------------------------------------


def test_inter_rule_max_moves_bias_up(tmp_path: Path, baseline, prompt_text: str, cset) -> None:
    candidate = aggregate.patch_constants(prompt_text, INTER_RULE="max")
    replayed = run.load_run(replay.replay_run(baseline, candidate, tmp_path / "max", now=clock))
    cmp = compare.compare(replayed, baseline, cset)
    assert cmp.passed
    bias = next(r for r in cmp.readings if r.metric == "Bias")
    # max over sections is never below the mean of the two best, so no total can fall.
    assert bias.difference.estimate is not None and bias.difference.estimate > 0
    assert bias.difference.low is not None and bias.difference.low >= 0
    assert cmp.candidate is not None and cmp.baseline is not None
    cand_tot = {p.paper: p.total for p in cmp.candidate.splits["calibration"].papers}
    base_tot = {p.paper: p.total for p in cmp.baseline.splits["calibration"].papers}
    assert all(cand_tot[p] >= base_tot[p] for p in cand_tot)
    for change in cmp.band_changes:
        assert cmp.candidate is not None
        assert change.baseline != change.candidate


def test_the_comment_format(tmp_path: Path, baseline, prompt_text: str, cset) -> None:
    candidate = aggregate.patch_constants(prompt_text, INTER_RULE="max")
    replayed = run.load_run(replay.replay_run(baseline, candidate, tmp_path / "max", now=clock))
    text = compare.render_comment(compare.compare(replayed, baseline, cset))
    lines = text.split("\n")
    assert lines[0].startswith("SYNTHETIC")
    n = len([p for p in PAPERS if cset.paper(p).split == "calibration"])
    assert lines[1] == (f"### Paperweight calibration · replay · {n} papers × 2 repeats · model shim-noisy"
                        " · partial (a subset of papers)")
    assert lines[2] == "Gates: 4 of 4 pass"
    assert "| Metric | Baseline | Candidate | Difference (95% interval) | Reading |" in lines
    assert any(x.startswith("| MAE | ") for x in lines)
    assert any(x.startswith("| Bias | +") or x.startswith("| Bias | -") for x in lines)
    assert any(x.startswith("| Correlation | ") for x in lines)
    assert any(x.startswith("Bands changed: ") for x in lines)
    assert any(x.startswith("Stability: sigma ") and "spans nested" in x for x in lines)
    assert "Holdout (1 paper, reported apart)" in text
    assert chr(0x2014) not in text  # no em dash


def test_no_baseline(baseline, cset) -> None:
    text = compare.render_comment(compare.compare(baseline, None, cset))
    assert "No baseline for model shim-noisy: this run can serve as one." in text
    assert text.startswith("SYNTHETIC")


def test_synthetic_and_real_runs_are_never_compared(tmp_path: Path, baseline, cset) -> None:
    real = tmp_path / "real"
    shutil.copytree(baseline.path, real)
    for path in [real / "meta.json", *real.glob("*.r*/result.json")]:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["synthetic"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(compare.CompareError, match="synthetic run with a real one"):
        compare.compare(run.load_run(real), baseline, cset)
    with pytest.raises(compare.CompareError, match="synthetic run with a real one"):
        compare.compare(baseline, run.load_run(real), cset)


def test_runs_on_different_models_are_not_compared(tmp_path: Path, prompt_text: str, baseline, cset) -> None:
    other = run.load_run(shim_run(tmp_path, prompt_text, cset, "cal", profile="calibrated"))
    with pytest.raises(compare.CompareError, match="that model's baseline"):
        compare.compare(other, baseline, cset)


def test_the_summary(baseline, cset) -> None:
    scores = score.score_run(baseline, cset)
    md = score.summary_markdown(scores)
    data = score.summary_json(scores)
    assert md.startswith("SYNTHETIC")
    assert data["synthetic"] is True
    assert set(data["splits"]) == {"calibration", "holdout"}
    cal = data["splits"]["calibration"]
    assert set(cal["criterion_bias"]) == set(cset.criteria)
    assert cal["stability"]["pairs"] == len(cal["papers"])
    assert data["health"]["runs"] == len(PAPERS) * 2


def test_triage_disagreement_is_flagged_not_gated(tmp_path: Path, baseline, cset) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(baseline.path, copy)

    def refuse(paper: str, repeat: int) -> None:
        result = copy / f"{paper}.r{repeat}" / "result.json"
        data = json.loads(result.read_text(encoding="utf-8"))
        data.update(is_proposal=False, weight_line="Weight: n/a", span="", shown=None, total=None, grades={})
        result.write_text(json.dumps(data), encoding="utf-8")

    refuse("P0957R8", 2)          # one of two repeats flips
    refuse("P3953R0", 1)          # every repeat refuses: consistent, not a disagreement
    refuse("P3953R0", 2)
    folder = run.load_run(copy)
    scores = score.score_run(folder, cset)
    assert scores.triage_splits == {"P0957R8": (1, 2)}
    assert scores.health["triage_disagreements"] == 1
    assert scores.excluded["P0957R8"] == "triage disagreed across repeats: 1 of 2 called it not a proposal"
    assert scores.excluded["P3953R0"] == "triaged NOT_PROPOSAL"
    cmp = compare.compare(folder, None, cset)
    assert cmp.passed
    text = compare.render_comment(cmp)
    assert "Triage disagreed across repeats: P0957R8 (1 of 2 called it not a proposal)" in text
    assert "Triage disagreed" in score.summary_markdown(scores)


def test_reading_from_test() -> None:
    def t(d, p):
        return metrics.PermutationTest(difference=d, p=p, patterns=64, exact=True)
    assert compare.reading_from_test(t(-0.5, 0.01), -1) == compare.BETTER
    assert compare.reading_from_test(t(0.5, 0.01), -1) == compare.WORSE
    assert compare.reading_from_test(t(0.5, 0.01), +1) == compare.BETTER
    assert compare.reading_from_test(t(-0.5, 0.2), -1) == compare.WITHIN_NOISE
    assert compare.reading_from_test(t(None, None), -1) == compare.NO_READING
