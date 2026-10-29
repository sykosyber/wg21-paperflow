# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Agreement and stability metrics, bootstrap intervals, paired differences.

The definitions follow the spec's two tables and the numbers recorded in
paperweight.md's comments:

- Agreement is per paper, against the reviewer mean. A paper's paperweight
  total is the mean of its completed repeats.
- Every agreement metric carries a 95% percentile bootstrap interval over
  papers: `BOOTSTRAP_RESAMPLES` resamples with replacement, drawn from
  `random.Random(seed)`, the interval read by nearest rank. A resample on
  which a statistic is undefined (a correlation with no variance) is
  dropped and counted.
- A comparison of two versions is paired by paper: each resample draws one
  set of papers and computes both versions on it.
- Whether a difference is real is decided by a paired permutation test, not
  by the bootstrap interval: on each paper the two versions' totals are
  swapped or not, and the difference is recomputed. With up to
  `EXACT_PERMUTATION_MAX` papers every swap pattern is tried, so the test is
  exact; above that `PERMUTATIONS` seeded patterns are drawn. On ICLR 2025's
  real reviews (studies/iclr-2025-reviewers.md) the percentile bootstrap
  called a no-change swap significant 12% of the time on ten papers, more
  than twice its nominal 5%; the permutation test keeps to its level.
- The grade-2 rate counts judgements at exactly 2. A paperweight grade is
  continuous under `top2` (two sections at 2 and 1.67 give 1.83), so a
  grade near 2 is not full marks.
- Bands use the epilogue's own rounding: a total is rounded half up before
  its band is looked up, as the verdict line does.
- Sigma is the sample standard deviation of a paper's totals across its
  repeats, averaged over papers with at least two completed repeats.

Standard library only.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261026
CONFIDENCE = 0.95
FULL_MARKS = 2
SIGNIFICANCE = 0.05
EXACT_PERMUTATION_MAX = 12   # 2**12 = 4,096 swap patterns
PERMUTATIONS = 2000

Stat = Callable[[Sequence[int]], "float | None"]
# A statistic of one version's totals against the reference totals.
PairStat = Callable[[Sequence[float], Sequence[float]], "float | None"]


@dataclass(frozen=True)
class PermutationTest:
    """Candidate minus baseline, and how often swapping the two per paper does as well."""

    difference: float | None
    p: float | None
    patterns: int
    exact: bool


def paired_permutation(stat: PairStat, cand: Sequence[float], base: Sequence[float],
                       reference: Sequence[float], *, seed: int = BOOTSTRAP_SEED,
                       exact_max: int = EXACT_PERMUTATION_MAX,
                       permutations: int = PERMUTATIONS) -> PermutationTest:
    """Two-sided paired permutation test of stat(cand) minus stat(base).

    Under no real difference the two versions are exchangeable on each
    paper, so swapping them on any subset of papers gives an equally likely
    difference. p is the share of swap patterns whose difference is at least
    as far from zero as the observed one. Up to `exact_max` papers, every
    pattern is tried; above that, `permutations` patterns are drawn with a
    fixed seed and p counts the observed pattern too. A pattern on which the
    statistic is undefined is skipped.
    """
    n = len(cand)

    def diff(mask: int) -> float | None:
        c = [base[i] if mask >> i & 1 else cand[i] for i in range(n)]
        b = [cand[i] if mask >> i & 1 else base[i] for i in range(n)]
        sc, sb = stat(c, reference), stat(b, reference)
        return None if sc is None or sb is None else sc - sb

    observed = diff(0)
    if observed is None or n == 0:
        return PermutationTest(observed, None, 0, n <= exact_max)
    tolerance = 1e-12 * max(1.0, abs(observed))
    if n <= exact_max:
        masks: Sequence[int] = range(2 ** n)
        extreme = total = 0
    else:
        rng = random.Random(seed)
        masks = [rng.getrandbits(n) for _ in range(permutations)]
        extreme = total = 1          # the observed pattern counts once
    for mask in masks:
        d = diff(mask)
        if d is None:
            continue
        total += 1
        extreme += abs(d) >= abs(observed) - tolerance
    return PermutationTest(observed, extreme / total if total else None, total, n <= exact_max)


@dataclass(frozen=True)
class Interval:
    """A point estimate and its bootstrap interval."""

    estimate: float | None
    low: float | None
    high: float | None
    used: int
    dropped: int

    def contains(self, value: float) -> bool:
        return self.low is not None and self.high is not None and self.low <= value <= self.high


# --- point statistics ---------------------------------------------------------


def mean(xs: Sequence[float]) -> float:
    return math.fsum(xs) / len(xs)


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson r; None when either side has no variance."""
    if len(xs) != len(ys):
        raise ValueError("pearson needs paired sequences")
    if len(xs) < 2:
        return None
    mx, my = mean(xs), mean(ys)
    sxy = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    syy = math.fsum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def bias(pw: Sequence[float], rev: Sequence[float]) -> float:
    """Mean of (paperweight minus reviewer mean)."""
    return mean([p - r for p, r in zip(pw, rev, strict=True)])


def mae(pw: Sequence[float], rev: Sequence[float]) -> float:
    """Mean absolute difference."""
    return mean([abs(p - r) for p, r in zip(pw, rev, strict=True)])


def reviewer_ceiling(totals: Sequence[Sequence[float]]) -> float | None:
    """Mean pairwise Pearson r between reviewers; `totals[r][p]` per reviewer."""
    rs = [pearson(a, b) for a, b in combinations(totals, 2)]
    defined = [r for r in rs if r is not None]
    if not defined or len(defined) != len(rs):
        return None
    return mean(defined)


def criterion_bias(pw: Sequence[Mapping[str, float]], rev: Sequence[Mapping[str, float]],
                   criterion: str) -> float:
    """Bias on one criterion's 0 to 2 scale: `pw[p]` and `rev[p]` map criterion to grade."""
    return bias([g[criterion] for g in pw], [g[criterion] for g in rev])


def grade2_count(grades: Sequence[float]) -> tuple[int, int]:
    """How many judgements award full marks, as (awarded 2, judgements).

    A paperweight grade is continuous under top2, so only an exact 2 counts.
    """
    return sum(1 for g in grades if g == FULL_MARKS), len(grades)


def band_agreement(pw_bands: Sequence[str], rev_bands: Sequence[str]) -> tuple[int, int]:
    """Papers whose band matches the reviewers' band, as (matching, papers)."""
    return sum(1 for a, b in zip(pw_bands, rev_bands, strict=True) if a == b), len(pw_bands)


# --- bootstrap ------------------------------------------------------------------


def nearest_rank(sorted_values: Sequence[float], q: float) -> float:
    """The nearest-rank q-quantile: the ceil(q * n)-th smallest value."""
    n = len(sorted_values)
    rank = max(1, math.ceil(q * n))
    return sorted_values[min(rank, n) - 1]


def resample_indices(n: int, resamples: int, seed: int) -> list[list[int]]:
    rng = random.Random(seed)
    return [[rng.randrange(n) for _ in range(n)] for _ in range(resamples)]


def bootstrap(stat: Stat, n: int, *, resamples: int = BOOTSTRAP_RESAMPLES,
              seed: int = BOOTSTRAP_SEED, confidence: float = CONFIDENCE) -> Interval:
    """Percentile bootstrap of `stat` over `n` papers."""
    estimate = stat(list(range(n))) if n else None
    if n == 0:
        return Interval(None, None, None, 0, 0)
    values = []
    dropped = 0
    for idx in resample_indices(n, resamples, seed):
        v = stat(idx)
        if v is None:
            dropped += 1
        else:
            values.append(v)
    if not values:
        return Interval(estimate, None, None, 0, dropped)
    values.sort()
    tail = (1 - confidence) / 2
    return Interval(estimate, nearest_rank(values, tail), nearest_rank(values, 1 - tail),
                    len(values), dropped)


def paired_difference(candidate: Stat, baseline: Stat, n: int, *,
                      resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED,
                      confidence: float = CONFIDENCE) -> Interval:
    """Bootstrap of candidate minus baseline, both on the same resampled papers."""
    def diff(idx: Sequence[int]) -> float | None:
        a, b = candidate(idx), baseline(idx)
        if a is None or b is None:
            return None
        return a - b
    return bootstrap(diff, n, resamples=resamples, seed=seed, confidence=confidence)


def pick(xs: Sequence[float], idx: Sequence[int]) -> list[float]:
    return [xs[i] for i in idx]


def bias_stat(pw: Sequence[float], rev: Sequence[float]) -> Stat:
    return lambda idx: bias(pick(pw, idx), pick(rev, idx))


def abs_bias_stat(pw: Sequence[float], rev: Sequence[float]) -> Stat:
    return lambda idx: abs(bias(pick(pw, idx), pick(rev, idx)))


def mae_stat(pw: Sequence[float], rev: Sequence[float]) -> Stat:
    return lambda idx: mae(pick(pw, idx), pick(rev, idx))


def pearson_stat(pw: Sequence[float], rev: Sequence[float]) -> Stat:
    return lambda idx: pearson(pick(pw, idx), pick(rev, idx))


def ceiling_stat(totals: Sequence[Sequence[float]]) -> Stat:
    return lambda idx: reviewer_ceiling([pick(t, idx) for t in totals])


def criterion_bias_stat(pw: Sequence[Mapping[str, float]], rev: Sequence[Mapping[str, float]],
                        criterion: str) -> Stat:
    return lambda idx: criterion_bias([pw[i] for i in idx], [rev[i] for i in idx], criterion)


# --- stability --------------------------------------------------------------------


@dataclass(frozen=True)
class Stability:
    """Run-to-run stability over papers with at least two completed repeats."""

    sigma: float | None
    pairs: int
    same_exact: int
    same_integer: int
    same_band: int
    spans_nested: int
    papers: int


def lua_round(x: float) -> int:
    return math.floor(x + 0.5)


def nested(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Two band spans, as (lowest, highest) band index, are equal or nested."""
    return (a[0] <= b[0] and b[1] <= a[1]) or (b[0] <= a[0] and a[1] <= b[1])


def stability(per_paper: Sequence[Sequence[tuple[float, str, tuple[int, int]]]]) -> Stability:
    """`per_paper[p]` lists (total, band, span) for each completed repeat.

    `band` is the band of the rounded total, as the verdict line shows it;
    `span` is the verdict line's span as band indices. Same exact compares
    totals as printed, to two decimals.
    """
    sigmas = []
    pairs = same_exact = same_int = same_band = nested_n = 0
    papers = 0
    for runs in per_paper:
        if len(runs) < 2:
            continue
        papers += 1
        sigmas.append(statistics.stdev([t for t, _, _ in runs]))
        for (ta, ba, sa), (tb, bb, sb) in combinations(runs, 2):
            pairs += 1
            same_exact += f"{ta:.2f}" == f"{tb:.2f}"
            same_int += lua_round(ta) == lua_round(tb)
            same_band += ba == bb
            nested_n += nested(sa, sb)
    return Stability(sigma=mean(sigmas) if sigmas else None, pairs=pairs,
                     same_exact=same_exact, same_integer=same_int, same_band=same_band,
                     spans_nested=nested_n, papers=papers)
