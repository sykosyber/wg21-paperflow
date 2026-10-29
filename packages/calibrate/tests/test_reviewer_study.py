# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The reviewer study's analysis, on tiny hand-made inputs (invented scores)."""

from __future__ import annotations

import pytest

from calibrate import reviewer_study as rs


def test_parse_scores() -> None:
    p = rs.parse_scores("x", ["2;4;4;3", "3;3;3;2", "3;4;3;3"], 1, 4)
    assert p is not None and p.reviewers == 4
    assert p.grades[0] == (2, 3, 3) and p.total(1) == 11
    assert rs.parse_scores("x", ["2;4", "3;3;3"], 1, 4) is None       # counts differ
    assert rs.parse_scores("x", ["2;5", "3;3"], 1, 4) is None          # out of range
    assert rs.parse_scores("x", ["", "3;3"], 1, 4) is None             # missing
    assert rs.parse_scores("x", ["2;a", "3;3"], 1, 4) is None          # not a number


def paper(name: str, totals: list[int]) -> rs.ReviewedPaper:
    """A one-criterion paper whose reviewers give these grades."""
    return rs.ReviewedPaper(paper=name, grades=tuple((t,) for t in totals))


def test_shuffling_keeps_each_reviewer_whole_and_is_seeded() -> None:
    papers = [rs.ReviewedPaper(paper=str(i), grades=((1, 1), (2, 2), (3, 3), (4, 4))) for i in range(20)]
    a = rs.shuffle_reviewers(papers, 1)
    assert a == rs.shuffle_reviewers(papers, 1)
    assert all(sorted(p.grades) == [(1, 1), (2, 2), (3, 3), (4, 4)] for p in a)
    assert any(p.grades[0] != (1, 1) for p in a)   # sorted input does not stay sorted
    assert a != rs.shuffle_reviewers(papers, 2)


def test_panels_split_the_reviewers() -> None:
    papers = [paper("a", [1, 3, 5, 7]), paper("b", [4, 4, 4]), paper("c", [2, 4, 4, 6, 8])]
    null = rs.panel(papers, 1)                     # b has too few reviewers and is left out
    assert null.base == (1.0, 2.0) and null.cand == (3.0, 4.0)
    assert null.reference == (6.0, 6.0)
    two = rs.panel(papers, 2)
    assert two.cand == (2.0, 3.0) and two.reference == (6.0, 6.0)
    three = rs.panel(papers, 3)                    # needs five reviewers: only c
    assert three.cand == (pytest.approx(10 / 3),) and three.reference == (7.0,)
    assert two.error_change == pytest.approx((4 + 3) / (5 + 4) - 1)


def test_ceiling_and_criterion_agreement() -> None:
    papers = [paper("a", [1, 1, 2]), paper("b", [2, 2, 3]), paper("c", [3, 3, 4])]
    assert rs.ceiling(papers, 3) == pytest.approx(1.0)
    same, r = rs.criterion_agreement(papers, 0)
    assert same == pytest.approx(1 / 3)   # of the three pairs per paper, only the first two reviewers agree
    assert r == pytest.approx(1.0)


def panel_of(cand_offset: int) -> rs.Panel:
    """Twelve papers: the baseline 2 off the reference, the candidate cand_offset off."""
    refs = [float(i) for i in range(1, 13)]
    return rs.Panel(label="x", base=tuple(r + 2 for r in refs), cand=tuple(r + cand_offset for r in refs),
                    reference=tuple(refs))


def test_a_uniform_gain_always_reads_better() -> None:
    res = rs.power(panel_of(0), 10, trials=20, seed=1, resamples=200)
    assert (res.better, res.worse) == (20, 0)


def test_no_change_never_raises_an_alarm() -> None:
    res = rs.power(panel_of(2), 10, trials=20, seed=1, resamples=200)
    assert (res.better, res.worse) == (0, 0)


def test_both_reading_methods_agree_on_clear_cases() -> None:
    for method in (rs.PERMUTATION, rs.BOOTSTRAP):
        assert rs.power(panel_of(0), 10, trials=10, seed=1, method=method, resamples=200).better == 10
        assert rs.power(panel_of(2), 10, trials=10, seed=1, method=method, resamples=200).better == 0
    assert rs.power(panel_of(0), 10, trials=1, seed=1).label == "x [permutation]"


def test_power_is_seeded() -> None:
    papers = [paper(str(i), [1 + i % 3, 2 + i % 2, 1 + i % 4, 2]) for i in range(30)]
    p = rs.panel(papers, 2)
    assert rs.power(p, 10, trials=15, seed=7, resamples=200) == rs.power(p, 10, trials=15, seed=7, resamples=200)
