# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""ICLR 2025 reviewers as a proxy: the harness's statistics on real human disagreement.

PROXY DATA. Real reviews of ICLR 2025, not paperweight's rubric; no number
here is a finding about paperweight.

    uv run python packages/calibrate/scripts/iclr_reviewer_study.py [--data FILE]

The reviews come from Paper Copilot's public list (papercopilot/paperlists,
iclr/iclr2025.json), pinned by sha256. That repository declares no license,
so the file is downloaded to --data (default calibration-runs/_data/, which
git ignores) and never committed; only the aggregate numbers are. The list
orders each paper's reviews by overall rating, so reviewers are shuffled
per paper, with a seed, before anything is computed. Writes
packages/calibrate/studies/iclr-2025-reviewers.{md,json}.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import urllib.request
from pathlib import Path

from calibrate import metrics, reviewer_study

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = "https://media.githubusercontent.com/media/papercopilot/paperlists/main/iclr/iclr2025.json"
SOURCE_SHA256 = "d288d0348d121671156481f0939312a45abbc5f95511c15c4b9a6e9675d19549"
DEFAULT_DATA = REPO_ROOT / "calibration-runs" / "_data" / "iclr2025.json"
OUT = REPO_ROOT / "packages" / "calibrate" / "studies"
CRITERIA = ("soundness", "presentation", "contribution")
GRADE_RANGE = (1, 4)
SAMPLE_SIZES = (10, 20, 40, 80)
PANELS = (1, 2, 3)  # 1 = the null: one reviewer swapped for another
PERM, BOOT = reviewer_study.PERMUTATION, reviewer_study.BOOTSTRAP
# (panel, reading method) rows of the table; the bootstrap rows show what the
# permutation test replaced.
ROWS = ((1, BOOT), (1, PERM), (2, BOOT), (2, PERM), (3, PERM))
TRIALS = 200
# Power uses 1,000 bootstrap resamples or drawn permutation patterns, not a
# real comparison's 2,000, to keep the study to minutes. Up to 12 papers the
# permutation test is exact whatever this says.
POWER_RESAMPLES = 1000
SEED = 20261027

log = logging.getLogger("iclr_reviewer_study")


def fetch(path: Path) -> bytes:
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        log.info("downloading %s", SOURCE)
        with urllib.request.urlopen(SOURCE, timeout=600) as resp:
            path.write_bytes(resp.read())
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit(f"{path} has sha256 {digest}, pinned {SOURCE_SHA256}")
    return data


def sorted_share(rows: list[dict]) -> float:
    """The share of papers with four or more reviews whose ratings come sorted."""
    seqs = [[int(x) for x in r["rating"].split(";")] for r in rows
            if r.get("rating") and all(x.isdigit() for x in r["rating"].split(";"))]
    long = [s for s in seqs if len(s) >= 4]
    return sum(1 for s in long if s == sorted(s)) / len(long)


def fmt_iv(iv: metrics.Interval, signed: bool = False) -> str:
    def f(x: float | None) -> str:
        return "n/a" if x is None else (f"{x:+.2f}" if signed else f"{x:.2f}")
    return f"{f(iv.estimate)} ({f(iv.low)} to {f(iv.high)})"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    rows = json.loads(fetch(args.data))
    parsed = [p for p in (reviewer_study.parse_scores(r.get("id", ""), [r.get(c, "") for c in CRITERIA],
                                                       *GRADE_RANGE) for r in rows) if p is not None]
    papers = reviewer_study.shuffle_reviewers(parsed, SEED)
    panels = {m: reviewer_study.panel(papers, m) for m in PANELS}
    null = panels[1]
    n_null = null.papers
    log.info("%d papers listed, %d with all three scores", len(rows), len(papers))

    base, ref = list(null.base), list(null.reference)
    agree = {
        "bias": metrics.bootstrap(metrics.bias_stat(base, ref), n_null),
        "mae": metrics.bootstrap(metrics.mae_stat(base, ref), n_null),
        "r": metrics.bootstrap(metrics.pearson_stat(base, ref), n_null),
    }
    ceilings = {k: reviewer_study.ceiling(papers, k) for k in (3, 4)}
    per_crit = {c: reviewer_study.criterion_agreement(papers, i) for i, c in enumerate(CRITERIA)}
    results = []
    for m, method in ROWS:
        for n in SAMPLE_SIZES:
            # The same seed per panel and size: both methods judge the same draws.
            res = reviewer_study.power(panels[m], n, trials=TRIALS, seed=SEED + 31 * m + n,
                                       method=method, resamples=POWER_RESAMPLES)
            log.info("%s, n=%d: better %d, worse %d of %d", res.label, n, res.better, res.worse, res.trials)
            results.append(res)
    write_report(rows, papers, panels, agree, ceilings, per_crit, results, sorted_share(rows))


def write_report(rows, papers, panels, agree, ceilings, per_crit, results, sorted_frac) -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    def res(m: int, n: int, method: str = PERM) -> reviewer_study.PowerResult:
        return next(r for r in results if r.label == f"{panels[m].label} [{method}]" and r.n == n)

    def alarms(n: int, method: str) -> float:
        return res(1, n, method).better_rate + res(1, n, method).worse_rate

    names = {PERM: "permutation test (now)", BOOT: "bootstrap interval (before)"}
    header = ["| Candidate against one reviewer | Reading | Error change, all papers | "
              + " | ".join(f"{n} papers" for n in SAMPLE_SIZES) + " |",
              "| --- | --- | --- | " + " | ".join("---" for _ in SAMPLE_SIZES) + " |"]
    rows_md = []
    for m, method in ROWS:
        p = panels[m]
        if m == 1:
            cells = [f"{alarms(n, method):.0%} false alarms" for n in SAMPLE_SIZES]
        else:
            cells = [f"{res(m, n, method).better_rate:.0%} better" for n in SAMPLE_SIZES]
        rows_md.append(f"| {p.label.capitalize()} ({p.papers:,} papers) | {names[method]} | "
                       f"{p.error_change:+.0%} | " + " | ".join(cells) + " |")
    crit_rows = [f"| {c} | {same:.0%} | {r:.2f} |" for c, (same, r) in per_crit.items()]
    two, three = panels[2], panels[3]
    md = f"""PROXY: real human reviews of ICLR 2025 (Paper Copilot's public list), not paperweight's rubric; nothing here is a finding about paperweight.

# How much reviewers agree, and how many papers a reading needs

The harness's own statistics, run on real human disagreement instead of
simulated reviewers. ICLR 2025 reviewers grade soundness, presentation and
contribution from 1 to 4. A paper's "total" here is their sum, 3 to 12,
standing in for paperweight's sum of seven criteria graded 0 to 2. The
scales differ, so the useful numbers are relative: how well reviewers
agree, and how often a real improvement is detected.

Data: {len(rows):,} papers listed, {len(papers):,} with all three scores.
The source is pinned by sha256 `{SOURCE_SHA256[:16]}...` and is not
committed, because its repository declares no license. The list orders
each paper's reviews by overall rating ({sorted_frac:.0%} of papers with four
or more reviews arrive sorted), so each paper's reviewers were shuffled with
a fixed seed first, keeping every reviewer's grades together. Unshuffled,
"reviewer 1" is the harshest reviewer, and every comparison is skewed.

## How many papers a reading needs

Each row compares a candidate with a single reviewer, both scored against
the mean of the other reviewers on the same paper. The cells show how often
the harness's MAE reading came out "better" over
{TRIALS} random draws of that many papers. The first row is no real change:
one reviewer swapped for another, so any reading other than "within noise"
is a false alarm, and its cells count those. The improvements are real
ones, not planted: the average of two or three actual reviewers, which cuts
the error unevenly, paper by paper. Each row is read two ways: by the
paired permutation test the harness now uses, and by the bootstrap interval
it used before, on the same draws.

{chr(10).join(header + rows_md)}

How to read it, with the harness's permutation test: a real improvement
that cuts the error by about {-two.error_change:.0%} (two reviewers averaged
instead of one) reads "better" {res(2, 10).better_rate:.0%} of the time on ten
papers, {res(2, 20).better_rate:.0%} on twenty, {res(2, 40).better_rate:.0%} on forty and
{res(2, 80).better_rate:.0%} on eighty. One that cuts it by about
{-three.error_change:.0%} reads "better" {res(3, 10).better_rate:.0%} of the time on ten
papers and {res(3, 80).better_rate:.0%} on eighty.

The false-alarm rate is what a 5% test should hold to about 5%. The
bootstrap interval the harness first used raised false alarms on
{alarms(10, BOOT):.0%} of ten-paper draws, because a percentile interval drawn
from so few papers is too narrow. The paired permutation test that replaced
it raises them on {alarms(10, PERM):.0%}, and on {alarms(80, PERM):.0%} at eighty
papers. The price is power on small samples: the two-reviewer
improvement reads "better" {res(2, 10, PERM).better_rate:.0%} of the time with the
test against {res(2, 10, BOOT).better_rate:.0%} with the interval, an interval
that, on the same draws, also called a non-change significant far too often. Each reading here uses {POWER_RESAMPLES:,} bootstrap resamples or drawn
permutation patterns, not the harness's 2,000, to keep the study to
minutes; up to twelve papers the test is exact.

## How much reviewers agree

| Measure | Value (95% interval) |
| --- | --- |
| Reviewer ceiling, 3 reviewers (mean pairwise r of totals) | {ceilings[3]:.2f} |
| Reviewer ceiling, 4 reviewers | {ceilings[4]:.2f} |
| One reviewer against the mean of the others: bias (a check, should be near 0) | {fmt_iv(agree['bias'], True)} |
| One reviewer against the mean of the others: MAE | {fmt_iv(agree['mae'])} |
| One reviewer against the mean of the others: r | {fmt_iv(agree['r'])} |

A single human reviewer, scored the way the harness scores paperweight,
reaches r = {agree['r'].estimate:.2f} against the other reviewers' mean. An
automated grader at that level agrees with the panel about as well as one
of its own members does.

| Criterion | Pairs giving the same grade | r, two reviewers |
| --- | --- | --- |
{chr(10).join(crit_rows)}
"""
    (OUT / "iclr-2025-reviewers.md").write_bytes(md.encode("utf-8"))
    data = {
        "proxy": True, "synthetic": False, "source": SOURCE, "source_sha256": SOURCE_SHA256,
        "papers_listed": len(rows), "papers_scored": len(papers), "ratings_sorted_share": sorted_frac,
        "shuffle_seed": SEED, "ceiling": ceilings,
        "human_as_system": {k: {"estimate": v.estimate, "low": v.low, "high": v.high} for k, v in agree.items()},
        "criteria": {c: {"same_grade": s, "r": r} for c, (s, r) in per_crit.items()},
        "panels": {p.label: {"papers": p.papers, "error_change": p.error_change} for p in panels.values()},
        "methods": {"permutation": "the harness reading", "bootstrap": "the reading it replaced"},
        "power": [{"label": r.label, "n": r.n, "trials": r.trials, "better": r.better, "worse": r.worse}
                  for r in results],
        "trials": TRIALS, "power_resamples": POWER_RESAMPLES,
    }
    (OUT / "iclr-2025-reviewers.json").write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
    log.info("wrote %s", OUT / "iclr-2025-reviewers.md")


if __name__ == "__main__":
    main()
