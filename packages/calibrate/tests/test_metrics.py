# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Metrics: known answers on tiny hand-computed sets, and planted truth
recovered through the whole pipeline (simulated grader, real Lua, parser)."""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import pytest

from calibrate import diagnostics, metrics, shim, simulate, synthetic

# --- known answers -----------------------------------------------------------


def test_bias_and_mae() -> None:
    # differences 1, 0, -2
    assert metrics.bias([3, 5, 7], [2, 5, 9]) == pytest.approx(-1 / 3)
    assert metrics.mae([3, 5, 7], [2, 5, 9]) == pytest.approx(1.0)


def test_pearson() -> None:
    assert metrics.pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert metrics.pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    # dx = dy up to a swap of the middle pair: sxy 4, sxx = syy = 5
    assert metrics.pearson([1, 2, 3, 4], [1, 3, 2, 4]) == pytest.approx(0.8)
    assert metrics.pearson([1, 1, 1], [1, 2, 3]) is None
    assert metrics.pearson([1], [2]) is None


def test_reviewer_ceiling() -> None:
    a, b, c = [1, 2, 3, 4], [1, 3, 2, 4], [4, 3, 2, 1]
    # r(a,b) = 0.8, r(a,c) = -1, r(b,c) = -0.8
    assert metrics.reviewer_ceiling([a, b, c]) == pytest.approx((0.8 - 1 - 0.8) / 3)
    assert metrics.reviewer_ceiling([a, [2, 2, 2, 2]]) is None


def test_criterion_bias_grade2_and_bands() -> None:
    pw = [{"prior_art": 2.0, "audience": 0.0}, {"prior_art": 1.5, "audience": 1.0}]
    rev = [{"prior_art": 1.0, "audience": 0.0}, {"prior_art": 1.5, "audience": 2.0}]
    assert metrics.criterion_bias(pw, rev, "prior_art") == pytest.approx(0.5)
    assert metrics.criterion_bias(pw, rev, "audience") == pytest.approx(-0.5)
    assert metrics.grade2_count([2.0, 5 / 3, 2.0, 0.0]) == (2, 4)
    assert metrics.band_agreement(["Medium", "Heavy", "Light"], ["Medium", "Medium", "Light"]) == (2, 3)


def test_nearest_rank() -> None:
    values = list(range(1, 2001))
    assert metrics.nearest_rank(values, 0.025) == 50
    assert metrics.nearest_rank(values, 0.975) == 1950
    assert metrics.nearest_rank([7.0], 0.025) == 7.0


def test_bootstrap_of_a_constant_collapses() -> None:
    pw, rev = [3.0, 4.0, 6.0], [2.0, 3.0, 5.0]
    iv = metrics.bootstrap(metrics.bias_stat(pw, rev), 3)
    assert (iv.estimate, iv.low, iv.high) == (1.0, 1.0, 1.0)
    assert iv.used == metrics.BOOTSTRAP_RESAMPLES and iv.dropped == 0


def test_bootstrap_of_two_papers_spans_every_resample_mean() -> None:
    # differences 0 and 2: a resample's mean is 0, 1 or 2 with odds 1:2:1, so
    # the 2.5% and 97.5% nearest ranks of 2,000 resamples are 0 and 2.
    iv = metrics.bootstrap(metrics.bias_stat([0.0, 2.0], [0.0, 0.0]), 2)
    assert (iv.estimate, iv.low, iv.high) == (1.0, 0.0, 2.0)


def test_bootstrap_is_seeded() -> None:
    pw, rev = [5.0, 7.0, 3.0, 9.0, 6.0], [4.0, 7.5, 3.0, 7.0, 6.5]
    a = metrics.bootstrap(metrics.mae_stat(pw, rev), 5)
    b = metrics.bootstrap(metrics.mae_stat(pw, rev), 5)
    assert a == b
    assert a.low <= a.estimate <= a.high
    seeded = metrics.resample_indices(5, 50, metrics.BOOTSTRAP_SEED)
    assert seeded == metrics.resample_indices(5, 50, metrics.BOOTSTRAP_SEED)
    assert seeded != metrics.resample_indices(5, 50, metrics.BOOTSTRAP_SEED + 1)


def test_correlation_drops_undefined_resamples() -> None:
    # Two papers: a resample of one paper twice has no variance.
    iv = metrics.bootstrap(metrics.pearson_stat([1.0, 2.0], [1.0, 3.0]), 2)
    assert iv.estimate == pytest.approx(1.0)
    assert iv.dropped > 0 and iv.used + iv.dropped == metrics.BOOTSTRAP_RESAMPLES
    assert (iv.low, iv.high) == (pytest.approx(1.0), pytest.approx(1.0))


def test_reviewer_ceiling_bootstrap() -> None:
    a, b, c = [1.0, 2.0, 3.0, 4.0], [1.0, 3.0, 2.0, 4.0], [1.0, 2.0, 4.0, 3.0]
    iv = metrics.bootstrap(metrics.ceiling_stat([a, b, c]), 4)
    assert iv.estimate == pytest.approx(metrics.reviewer_ceiling([a, b, c]))
    assert iv.low is not None and iv.low <= iv.estimate <= iv.high <= 1.0


def test_paired_difference_of_a_shift() -> None:
    base, rev = [5.0, 7.0, 3.0, 9.0], [4.0, 7.0, 3.0, 7.0]
    cand = [x + 0.5 for x in base]
    iv = metrics.paired_difference(metrics.bias_stat(cand, rev), metrics.bias_stat(base, rev), 4)
    assert (iv.estimate, iv.low, iv.high) == (0.5, 0.5, 0.5)
    # pairing matters: an unpaired MAE difference would not be exactly zero
    same = metrics.paired_difference(metrics.mae_stat(base, rev), metrics.mae_stat(base, rev), 4)
    assert (same.low, same.high) == (0.0, 0.0)


def test_paired_difference_uses_one_draw_for_both_versions() -> None:
    rev = [0.0, 0.0]
    base = [0.0, 2.0]
    cand = [2.0, 2.0]
    # cand - base is 2 on paper 0 and 0 on paper 1; its resampled bias differences
    # are 0, 1 or 2, never anything an independent draw could produce, like -1.
    iv = metrics.paired_difference(metrics.bias_stat(cand, rev), metrics.bias_stat(base, rev), 2)
    assert (iv.estimate, iv.low, iv.high) == (1.0, 0.0, 2.0)


def test_stability() -> None:
    runs = [
        [(6.0, "Medium", (2, 2)), (6.33, "Medium", (2, 2))],
        [(7.67, "Heavy", (2, 3)), (7.0, "Medium", (2, 2))],
        [(4.0, "Medium", (2, 2))],  # one repeat: not counted
    ]
    s = metrics.stability(runs)
    assert (s.papers, s.pairs) == (2, 2)
    assert (s.same_exact, s.same_integer, s.same_band, s.spans_nested) == (0, 1, 1, 2)
    expected = (math.sqrt((0.33 ** 2) / 2) + math.sqrt((0.67 ** 2) / 2)) / 2
    assert s.sigma == pytest.approx(expected)


def test_nested_spans() -> None:
    assert metrics.nested((1, 3), (2, 2))
    assert metrics.nested((2, 2), (2, 2))
    assert not metrics.nested((1, 2), (2, 3))


# --- planted truth through the whole pipeline ----------------------------------

SET_DIR = Path(__file__).resolve().parents[1] / "data" / "synthetic"


def calibration_papers() -> list[tuple[str, str]]:
    rows = [json.loads(x) for x in (SET_DIR / "papers.jsonl").read_text(encoding="utf-8").splitlines()]
    return [(r["paper"], (SET_DIR / "papers" / f"{r['paper']}.md").read_bytes().decode("utf-8"))
            for r in rows if r["split"] == "calibration"]


def pipeline(prompt_text: str, profile: simulate.GraderProfile, noise_seed: int = 77):
    """Per paper: (paperweight total, grades) from the Lua, and the latent truth."""
    pw_totals, pw_grades, truth_totals, truth_grades = [], [], [], []
    for pid, text in calibration_papers():
        grader = simulate.SimulatedGrader(profile, truth_seed=synthetic.TRUTH_SEED, noise_seed=noise_seed)
        jobs: list[shim.GradeJob] = []

        def provider(job: shim.GradeJob, grader=grader, jobs=jobs) -> str | None:
            jobs.append(job)
            return grader(job)

        run = shim.run_paper(prompt_text, text, provider, paper_id=pid)
        d = diagnostics.parse_diagnostics(run.diagnostics)
        latent = grader.latent(jobs[0])
        pw_totals.append(float(d.points))
        pw_grades.append({k: float(v) for k, v in (d.grades or {}).items()})
        truth_totals.append(latent.total)
        truth_grades.append(dict(latent.truth))
    return pw_totals, pw_grades, truth_totals, truth_grades


def test_zero_noise_recovers_the_truth_exactly(prompt_text: str) -> None:
    exact = dataclasses.replace(simulate.PROFILES["calibrated"], sigma=0.0)
    pw, _, truth, _ = pipeline(prompt_text, exact)
    assert metrics.mae(pw, truth) == 0
    assert metrics.bias(pw, truth) == 0
    assert metrics.pearson(pw, truth) == pytest.approx(1.0)


@pytest.mark.parametrize("sigma", [0.0, simulate.DEFAULT_SIGMA])
def test_a_planted_bias_of_one_is_recovered(prompt_text: str, sigma: float) -> None:
    planted = dataclasses.replace(simulate.PROFILES["calibrated"], sigma=sigma, raise_steps=1)
    pw, _, truth, _ = pipeline(prompt_text, planted)
    iv = metrics.bootstrap(metrics.bias_stat(pw, truth), len(pw))
    assert iv.contains(1.0), iv
    if sigma == 0.0:
        assert iv.estimate == pytest.approx(1.0)


def test_prior_art_overgrade_shows_on_prior_art_only(prompt_text: str) -> None:
    _, over, _, truth = pipeline(prompt_text, simulate.PROFILES["prior_art_overgrade"])
    _, cal, _, _ = pipeline(prompt_text, simulate.PROFILES["calibrated"])
    n = len(over)
    for criterion in truth[0]:
        iv = metrics.bootstrap(metrics.criterion_bias_stat(over, truth, criterion), n)
        if criterion == "prior_art":
            assert iv.low is not None and iv.low > 0, iv
        else:
            assert iv.contains(0.0), (criterion, iv)
            # The bias moves no other criterion's grades at all.
            assert [g[criterion] for g in over] == [g[criterion] for g in cal]


# --- the paired permutation test ------------------------------------------------


def test_permutation_on_three_papers_can_never_be_significant() -> None:
    # Candidate exact, baseline 1 off on each paper. Of the 2**3 swap patterns,
    # the observed one and the full swap are equally extreme: p = 2/8.
    ref = [3.0, 5.0, 7.0]
    t = metrics.paired_permutation(metrics.mae, ref, [4.0, 6.0, 8.0], ref)
    assert (t.difference, t.p, t.patterns, t.exact) == (-1.0, 0.25, 8, True)


def test_permutation_on_six_consistent_papers_is_significant() -> None:
    ref = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    t = metrics.paired_permutation(metrics.mae, ref, [x + 1 for x in ref], ref)
    assert t.p == pytest.approx(2 / 64)


def test_permutation_of_a_balanced_change_is_not_significant() -> None:
    ref = [1.0, 2.0, 3.0, 4.0]
    cand = [1.0, 2.0, 5.0, 6.0]      # worse on two papers
    base = [3.0, 4.0, 3.0, 4.0]      # worse on the other two, by as much
    t = metrics.paired_permutation(metrics.mae, cand, base, ref)
    assert t.difference == 0 and t.p == 1.0


def test_permutation_samples_above_the_exact_limit_with_a_seed() -> None:
    ref = [float(i) for i in range(20)]
    base = [x + 1 for x in ref]
    a = metrics.paired_permutation(metrics.mae, ref, base, ref, permutations=500)
    b = metrics.paired_permutation(metrics.mae, ref, base, ref, permutations=500)
    assert a == b and not a.exact and a.patterns == 501
    assert a.p is not None and a.p < 0.01


def test_permutation_skips_undefined_patterns() -> None:
    ref = [1.0, 2.0, 3.0]
    cand = [5.0, 5.0, 5.0]           # no variance: r is undefined
    t = metrics.paired_permutation(metrics.pearson, cand, [1.0, 2.0, 3.0], ref)
    assert t.difference is None and t.p is None
