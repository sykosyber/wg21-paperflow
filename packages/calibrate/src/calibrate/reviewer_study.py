# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""How much do human reviewers agree, and how many papers does a reading need?

PROXY DATA: real human reviews of a public venue, not paperweight's rubric.
Nothing here is a finding about paperweight; it measures the harness's own
statistics on real human disagreement.

Input is one `ReviewedPaper` per paper: each reviewer's grade on each
criterion, aligned by reviewer. A published list may order reviewers by
their scores, which makes "reviewer 1" a systematically harsh or lenient
one, so `shuffle_reviewers` puts each paper's reviewers in a seeded random
order first, keeping every reviewer's grades together.

Everything is computed with the harness's own `metrics` and
`compare.reading_for`, so the numbers describe the harness:

- `ceiling`: mean pairwise Pearson r between reviewers' totals.
- `panel`: a comparison built from real reviewers. The baseline "system" is
  one reviewer; the candidate is either another single reviewer (no real
  change, so any reading but "within noise" is a false alarm) or the mean
  of m reviewers (a real improvement, of whatever size the data gives); the
  reference is the mean of the reviewers left over.
- `power`: how often the harness's paired-bootstrap MAE reading calls the
  candidate better or worse on n papers drawn at random.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

from calibrate import metrics
from calibrate.compare import BETTER, WORSE, reading_for, reading_from_test

MIN_REFERENCE = 2  # reviewers averaged into the reference, at least


@dataclass(frozen=True)
class ReviewedPaper:
    paper: str
    grades: tuple[tuple[int, ...], ...]  # grades[r][c]: reviewer r, criterion c

    @property
    def reviewers(self) -> int:
        return len(self.grades)

    def total(self, r: int) -> int:
        return sum(self.grades[r])

    def mean_total(self, reviewers: Sequence[int]) -> float:
        return metrics.mean([self.total(r) for r in reviewers])


def parse_scores(paper: str, fields: Sequence[str], lo: int, hi: int) -> ReviewedPaper | None:
    """One paper from per-criterion strings such as '2;4;4;3', aligned by reviewer.

    None when a criterion is missing, the reviewer counts differ, or a grade
    falls outside lo..hi.
    """
    columns = []
    for field in fields:
        if not field:
            return None
        try:
            values = [int(x) for x in field.split(";")]
        except ValueError:
            return None
        if any(not lo <= v <= hi for v in values):
            return None
        columns.append(values)
    if len({len(c) for c in columns}) != 1:
        return None
    return ReviewedPaper(paper=paper, grades=tuple(zip(*columns, strict=True)))


def shuffle_reviewers(papers: Sequence[ReviewedPaper], seed: int) -> list[ReviewedPaper]:
    """Each paper's reviewers in a seeded random order, every reviewer's grades kept together."""
    out = []
    for p in papers:
        order = list(p.grades)
        random.Random(f"{seed}|{p.paper}").shuffle(order)
        out.append(ReviewedPaper(paper=p.paper, grades=tuple(order)))
    return out


def ceiling(papers: Sequence[ReviewedPaper], k: int) -> float | None:
    """Mean pairwise r between reviewer slots 0..k-1, over papers with at least k reviewers."""
    usable = [p for p in papers if p.reviewers >= k]
    return metrics.reviewer_ceiling([[float(p.total(r)) for p in usable] for r in range(k)])


def criterion_agreement(papers: Sequence[ReviewedPaper], c: int) -> tuple[float, float | None]:
    """For one criterion: the share of reviewer pairs, over every pair on every
    paper, giving the same grade; and Pearson r between the first two reviewers."""
    same = pairs = 0
    for p in papers:
        for a, b in combinations(range(p.reviewers), 2):
            pairs += 1
            same += p.grades[a][c] == p.grades[b][c]
    two = [p for p in papers if p.reviewers >= 2]
    r = metrics.pearson([float(p.grades[0][c]) for p in two], [float(p.grades[1][c]) for p in two])
    return (same / pairs if pairs else 0.0), r


@dataclass(frozen=True)
class Panel:
    """A comparison built from real reviewers, one entry per usable paper."""

    label: str
    base: tuple[float, ...]
    cand: tuple[float, ...]
    reference: tuple[float, ...]

    @property
    def papers(self) -> int:
        return len(self.base)

    @property
    def error_change(self) -> float:
        """The candidate's MAE over the baseline's, minus one, across every usable paper."""
        return metrics.mae(self.cand, self.reference) / metrics.mae(self.base, self.reference) - 1


def panel(papers: Sequence[ReviewedPaper], m: int) -> Panel:
    """Baseline reviewer 0 against a candidate, both read against the reviewers left over.

    m = 1: the candidate is reviewer 1 alone, which is no real change. m >= 2:
    the candidate is the mean of reviewers 0..m-1. The reference is the mean
    of the reviewers after the candidate's, at least MIN_REFERENCE of them.
    """
    used = max(m, 2)
    usable = [p for p in papers if p.reviewers >= used + MIN_REFERENCE]
    label = "one reviewer swapped for another" if m == 1 else f"mean of {m} reviewers instead of one"
    return Panel(
        label=label,
        base=tuple(float(p.total(0)) for p in usable),
        cand=tuple(float(p.total(1)) if m == 1 else p.mean_total(range(m)) for p in usable),
        reference=tuple(p.mean_total(range(used, p.reviewers)) for p in usable))


@dataclass(frozen=True)
class PowerResult:
    label: str
    n: int
    trials: int
    better: int
    worse: int

    @property
    def better_rate(self) -> float:
        return self.better / self.trials

    @property
    def worse_rate(self) -> float:
        return self.worse / self.trials


PERMUTATION, BOOTSTRAP = "permutation", "bootstrap"


def power(p: Panel, n: int, *, trials: int, seed: int, method: str = PERMUTATION,
          resamples: int = metrics.BOOTSTRAP_RESAMPLES) -> PowerResult:
    """How often the MAE reading says better or worse on n papers drawn at random.

    `method` is the harness's reading, the paired permutation test, or
    "bootstrap": the percentile-interval reading it replaced, kept to show
    the difference. `resamples` sets the bootstrap's resamples or, above the
    exact limit, the permutation test's drawn patterns.
    """
    rng = random.Random(seed)
    better = worse = 0
    for t in range(trials):
        idx = rng.sample(range(p.papers), n)
        ref = [p.reference[i] for i in idx]
        base = [p.base[i] for i in idx]
        cand = [p.cand[i] for i in idx]
        if method == BOOTSTRAP:
            iv = metrics.paired_difference(metrics.mae_stat(cand, ref), metrics.mae_stat(base, ref), n,
                                           resamples=resamples, seed=seed * 100_003 + t)
            reading = reading_for(iv, -1)
        else:
            test = metrics.paired_permutation(metrics.mae, cand, base, ref,
                                              seed=seed * 100_003 + t, permutations=resamples)
            reading = reading_from_test(test, -1)
        better += reading == BETTER
        worse += reading == WORSE
    return PowerResult(label=f"{p.label} [{method}]", n=n, trials=trials, better=better, worse=worse)
