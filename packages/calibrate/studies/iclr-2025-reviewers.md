PROXY: real human reviews of ICLR 2025 (Paper Copilot's public list), not paperweight's rubric; nothing here is a finding about paperweight.

# How much reviewers agree, and how many papers a reading needs

The harness's own statistics, run on real human disagreement instead of
simulated reviewers. ICLR 2025 reviewers grade soundness, presentation and
contribution from 1 to 4. A paper's "total" here is their sum, 3 to 12,
standing in for paperweight's sum of seven criteria graded 0 to 2. The
scales differ, so the useful numbers are relative: how well reviewers
agree, and how often a real improvement is detected.

Data: 11,677 papers listed, 11,521 with all three scores.
The source is pinned by sha256 `d288d0348d121671...` and is not
committed, because its repository declares no license. The list orders
each paper's reviews by overall rating (100% of papers with four
or more reviews arrive sorted), so each paper's reviewers were shuffled with
a fixed seed first, keeping every reviewer's grades together. Unshuffled,
"reviewer 1" is the harshest reviewer, and every comparison is skewed.

## How many papers a reading needs

Each row compares a candidate with a single reviewer, both scored against
the mean of the other reviewers on the same paper. The cells show how often
the harness's MAE reading came out "better" over
200 random draws of that many papers. The first row is no real change:
one reviewer swapped for another, so any reading other than "within noise"
is a false alarm, and its cells count those. The improvements are real
ones, not planted: the average of two or three actual reviewers, which cuts
the error unevenly, paper by paper. Each row is read two ways: by the
paired permutation test the harness now uses, and by the bootstrap interval
it used before, on the same draws.

| Candidate against one reviewer | Reading | Error change, all papers | 10 papers | 20 papers | 40 papers | 80 papers |
| --- | --- | --- | --- | --- | --- | --- |
| One reviewer swapped for another (9,784 papers) | bootstrap interval (before) | +1% | 12% false alarms | 6% false alarms | 5% false alarms | 5% false alarms |
| One reviewer swapped for another (9,784 papers) | permutation test (now) | +1% | 4% false alarms | 2% false alarms | 2% false alarms | 4% false alarms |
| Mean of 2 reviewers instead of one (9,784 papers) | bootstrap interval (before) | -19% | 18% better | 28% better | 44% better | 72% better |
| Mean of 2 reviewers instead of one (9,784 papers) | permutation test (now) | -19% | 8% better | 18% better | 39% better | 70% better |
| Mean of 3 reviewers instead of one (2,051 papers) | permutation test (now) | -25% | 14% better | 28% better | 58% better | 87% better |

How to read it, with the harness's permutation test: a real improvement
that cuts the error by about 19% (two reviewers averaged
instead of one) reads "better" 8% of the time on ten
papers, 18% on twenty, 39% on forty and
70% on eighty. One that cuts it by about
25% reads "better" 14% of the time on ten
papers and 87% on eighty.

The false-alarm rate is what a 5% test should hold to about 5%. The
bootstrap interval the harness first used raised false alarms on
12% of ten-paper draws, because a percentile interval drawn
from so few papers is too narrow. The paired permutation test that replaced
it raises them on 4%, and on 4% at eighty
papers. The price is power on small samples: the two-reviewer
improvement reads "better" 8% of the time with the
test against 18% with the interval, an interval
that, on the same draws, also called a non-change significant far too often. Each reading here uses 1,000 bootstrap resamples or drawn
permutation patterns, not the harness's 2,000, to keep the study to
minutes; up to twelve papers the test is exact.

## How much reviewers agree

| Measure | Value (95% interval) |
| --- | --- |
| Reviewer ceiling, 3 reviewers (mean pairwise r of totals) | 0.24 |
| Reviewer ceiling, 4 reviewers | 0.24 |
| One reviewer against the mean of the others: bias (a check, should be near 0) | +0.00 (-0.03 to +0.04) |
| One reviewer against the mean of the others: MAE | 1.41 (1.39 to 1.43) |
| One reviewer against the mean of the others: r | 0.32 (0.30 to 0.34) |

A single human reviewer, scored the way the harness scores paperweight,
reaches r = 0.32 against the other reviewers' mean. An
automated grader at that level agrees with the panel about as well as one
of its own members does.

| Criterion | Pairs giving the same grade | r, two reviewers |
| --- | --- | --- |
| soundness | 45% | 0.17 |
| presentation | 43% | 0.17 |
| contribution | 45% | 0.19 |
