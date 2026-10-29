# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The simulated grader, run through the real Lua by the shim."""

from __future__ import annotations

import dataclasses
import re

import pytest

from calibrate import shim, simulate

PAPERS = [("p3978r0", "P3978R0"), ("p0533r9", "P0533R9"), ("p4228r0", "P4228R0"),
          ("p1068r11", "P1068R11")]


def grades_line(diagnostics: str) -> dict[str, float]:
    line = next(x for x in diagnostics.split("\n") if x.startswith("grades: "))
    return {k: float(v) for k, v in re.findall(r"(\S+) (\d+\.\d\d)", line[len("grades: "):])}


def recording(provider):
    seen: list[tuple[shim.GradeJob, str | None]] = []

    def wrapped(job: shim.GradeJob) -> str | None:
        reply = provider(job)
        seen.append((job, reply))
        return reply
    return wrapped, seen


def test_every_prompt_criterion_has_a_prior(prompt_text: str) -> None:
    assert set(shim.prompt_criteria(prompt_text)) == set(simulate.GRADE_PRIORS)


def test_votes_are_deterministic_and_order_free(prompt_text: str, ideal_paper) -> None:
    jobs: list[shim.GradeJob] = []

    def collect(job: shim.GradeJob) -> str:
        jobs.append(job)
        return "SCORE: 0\nQUOTE: "

    shim.run_paper(prompt_text, ideal_paper("p3978r0"), collect, paper_id="P3978R0")
    profile = simulate.PROFILES["noisy"]
    forward = simulate.SimulatedGrader(profile, truth_seed=11, noise_seed=12)
    backward = simulate.SimulatedGrader(profile, truth_seed=11, noise_seed=12)
    a = [forward(j) for j in jobs]
    b = [backward(j) for j in reversed(jobs)][::-1]
    assert a == b
    other = simulate.SimulatedGrader(profile, truth_seed=11, noise_seed=13)
    assert [other(j) for j in jobs] != a


@pytest.mark.parametrize(("stem", "pid"), PAPERS)
def test_zero_noise_reproduces_the_latent_truth(prompt_text: str, ideal_paper,
                                                stem: str, pid: str) -> None:
    exact = dataclasses.replace(simulate.PROFILES["calibrated"], sigma=0.0)
    grader = simulate.SimulatedGrader(exact, truth_seed=5, noise_seed=6)
    provider, seen = recording(grader)
    run = shim.run_paper(prompt_text, ideal_paper(stem), provider, paper_id=pid)
    latent = grader.latent(seen[0][0])
    assert grades_line(run.diagnostics) == latent.truth
    assert "Unsupported quotes rejected: 0." in run.diagnostics


@pytest.mark.parametrize(("stem", "pid"), PAPERS)
def test_every_quote_passes_the_lua_check(prompt_text: str, ideal_paper, stem: str, pid: str) -> None:
    grader = simulate.SimulatedGrader(simulate.PROFILES["noisy"], truth_seed=1, noise_seed=2)
    provider, seen = recording(grader)
    run = shim.run_paper(prompt_text, ideal_paper(stem), provider, paper_id=pid)
    assert "Unsupported quotes rejected: 0." in run.diagnostics
    nonzero = [r for _, r in seen if r and not r.startswith("SCORE: 0")]
    assert nonzero, "the noisy grader should award something"
    paper = ideal_paper(stem)
    for reply in nonzero:
        quote = reply.split("QUOTE: ", 1)[1]
        assert simulate.quote_passes(quote, paper), quote


def test_invalid_quote_share_is_rejected_by_the_lua(prompt_text: str, ideal_paper) -> None:
    profile = dataclasses.replace(simulate.PROFILES["noisy"], invalid_quote_rate=0.3)
    grader = simulate.SimulatedGrader(profile, truth_seed=1, noise_seed=2)
    run = shim.run_paper(prompt_text, ideal_paper("p0533r9"), grader, paper_id="P0533R9")
    assert grader.invalid_quotes > 0
    assert f"Unsupported quotes rejected: {grader.invalid_quotes}." in run.diagnostics
    assert not simulate.quote_passes(simulate.INVALID_QUOTE, ideal_paper("p0533r9"))


def test_missing_share_is_counted_by_the_lua(prompt_text: str, ideal_paper) -> None:
    profile = dataclasses.replace(simulate.PROFILES["calibrated"], missing_rate=0.05)
    grader = simulate.SimulatedGrader(profile, truth_seed=1, noise_seed=2)
    run = shim.run_paper(prompt_text, ideal_paper("p4228r0"), grader, paper_id="P4228R0")
    assert grader.missing > 0
    assert f"Replies missing: {grader.missing}." in run.diagnostics


def test_bookkeeping_sections_get_zero(prompt_text: str, ideal_paper) -> None:
    grader = simulate.SimulatedGrader(simulate.PROFILES["noisy"], truth_seed=1, noise_seed=2)
    provider, seen = recording(grader)
    shim.run_paper(prompt_text, ideal_paper("p3978r0"), provider, paper_id="P3978R0")
    bookkeeping = [(j, r) for j, r in seen if simulate.is_bookkeeping(j.chunk_title)]
    assert {j.chunk_title for j, _ in bookkeeping} >= {"1 CHANGELOG", "5 WORDING"}
    assert all(r == "SCORE: 0\nQUOTE: " for _, r in bookkeeping)


@pytest.mark.parametrize(("title", "expected"), [
    ("Revision history", True), ("1 CHANGELOG", True), ("Acknowledgements", True),
    ("Acknowledgments", True), ("References", True), ("Proposed wording", True),
    ("2 STRAW POLLS", True), ("Reference implementation", False), ("Motivation", False),
    ("Design", False), ("(front matter: title, abstract and anything before the first heading)", False),
])
def test_bookkeeping_headings(title: str, expected: bool) -> None:
    assert simulate.is_bookkeeping(title) is expected


def test_a_bias_moves_only_its_own_criterion(prompt_text: str, ideal_paper) -> None:
    def votes(profile_name: str) -> dict[tuple[str, int, int], str | None]:
        grader = simulate.SimulatedGrader(simulate.PROFILES[profile_name], truth_seed=3, noise_seed=4)
        provider, seen = recording(grader)
        shim.run_paper(prompt_text, ideal_paper("p1068r11"), provider, paper_id="P1068R11")
        return {(j.short, j.chunk, j.sample): r for j, r in seen}

    calibrated = votes("calibrated")
    overgrade = votes("prior_art_overgrade")
    changed = {k[0] for k in calibrated if calibrated[k] != overgrade[k]}
    assert changed == {"prior_art"}

    def score(reply: str | None) -> int:
        return int(reply.split("\n")[0].split()[1]) if reply else 0
    prior = [k for k in calibrated if k[0] == "prior_art"]
    assert sum(score(overgrade[k]) for k in prior) > sum(score(calibrated[k]) for k in prior)


def test_all_zero_profile_scores_nothing(prompt_text: str, ideal_paper) -> None:
    grader = simulate.SimulatedGrader(simulate.PROFILES["all_zero"], truth_seed=1, noise_seed=2)
    run = shim.run_paper(prompt_text, ideal_paper("p0533r9"), grader, paper_id="P0533R9")
    assert run.report.startswith("Weight: Weightless (0/14)")


def test_raise_steps_plants_one_grade_per_step(prompt_text: str, ideal_paper) -> None:
    exact = dataclasses.replace(simulate.PROFILES["calibrated"], sigma=0.0, raise_steps=1)
    grader = simulate.SimulatedGrader(exact, truth_seed=5, noise_seed=6)
    provider, seen = recording(grader)
    run = shim.run_paper(prompt_text, ideal_paper("p0533r9"), provider, paper_id="P0533R9")
    latent = grader.latent(seen[0][0])
    graded = grades_line(run.diagnostics)
    assert sum(graded.values()) == pytest.approx(latent.total + 1)
    assert sum(1 for s in graded if graded[s] != latent.truth[s]) == 1


def test_lua_normalize_matches_lua_string_semantics() -> None:
    # Lua's lower() touches ASCII only, and %s does not match a no-break space.
    assert simulate.lua_normalize("  ÉCOLE Paris\r\nX ") == "École paris x"
