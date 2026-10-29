# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Compare a candidate run with a baseline: gates, readings, band changes, comment.

Gates are yes/no properties, and any one failing fails the job:

1. Every run exits 0 and its report starts with a Weight line the prompt's
   own format would produce.
2. No run reports missing replies.
3. Every criterion in grades.csv is in the prompt's CRITERIA, and the reverse.
4. Replay parity holds on every recorded run.

A replay inherits gates 1, 2 and 4 from the full run it replays.

Two sampled properties are flagged on the comment and never gated: band
spans that fail to nest across repeats, and papers whose repeats disagree on
whether they are proposals (a flip turns a verdict into `Weight: n/a`).

Readings inform and never fail the job. For MAE, bias and correlation the
paired difference (candidate minus baseline) over the calibration papers both
runs completed is shown with its bootstrap interval. Whether it is real is
decided by a paired permutation test (`metrics.paired_permutation`): better
when p < 0.05 and the difference is on the improving side, worse when on the
other, within noise otherwise. The spec read it from the interval instead;
on ten papers that interval is too narrow (studies/iclr-2025-reviewers.md),
so the test replaces it. For bias the improving side is a smaller absolute
bias, so the test uses |bias| while the table shows the signed difference.

A synthetic run is never compared with a real one, in either direction, and
runs on different models are not compared: each model has its own baseline.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from calibrate import metrics
from calibrate.golden import CalibrationSet
from calibrate.marking import SYNTHETIC
from calibrate.replay import REPLAY, run_parity
from calibrate.run import FAILED, RunFolder, load_run
from calibrate.score import RunScores, SplitScores, fmt, score_run, triage_line
from calibrate.shim import PromptStructureError, prompt_criteria

BETTER, WITHIN_NOISE, WORSE, NO_READING = "better", "within noise", "worse", "n/a"
CALIBRATION, HOLDOUT = "calibration", "holdout"

COMMENT_BANNER = (
    f"{SYNTHETIC}: this comparison is built from synthetic grades or the Lua shim; "
    "its numbers say nothing about paperweight."
)


class CompareError(ValueError):
    """Two runs that must not be compared."""


@dataclass(frozen=True)
class Gate:
    number: int
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class Reading:
    metric: str
    baseline: float | None
    candidate: float | None
    difference: metrics.Interval
    reading: str
    signed: bool
    p: float | None = None


@dataclass(frozen=True)
class BandChange:
    paper: str
    baseline: str
    candidate: str
    reviewers: str


@dataclass(frozen=True)
class Comparison:
    """Gates always; scores and readings only when the criteria match (gate 3)."""

    candidate_run: RunFolder
    baseline_run: RunFolder | None
    candidate: RunScores | None
    baseline: RunScores | None
    gates: tuple[Gate, ...]
    readings: tuple[Reading, ...]
    band_changes: tuple[BandChange, ...]
    papers: tuple[str, ...]

    @property
    def synthetic(self) -> bool:
        return self.candidate_run.synthetic or (
            self.baseline_run is not None and self.baseline_run.synthetic)

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)


# --- gates ---------------------------------------------------------------------


def weight_line_re(labels: tuple[tuple[int, str], ...]) -> re.Pattern[str]:
    band = "(?:" + "|".join(re.escape(label) for _, label in labels) + ")"
    return re.compile(rf"^Weight: (?:n/a|{band}(?: to {band})? \(\d+/\d+\))$")


def source_of(folder: RunFolder) -> RunFolder:
    """The full run whose recorded runs a folder's gates rest on."""
    if folder.meta.get("mode") != REPLAY:
        return folder
    return load_run(Path(folder.meta["from_run"]))


def gates(folder: RunFolder, cset: CalibrationSet) -> tuple[Gate, ...]:
    source = source_of(folder)
    pattern = weight_line_re(folder.constants.labels)
    failed = [f"{r['paper']}.r{r['repeat']} ({r.get('error') or 'failed'})"
              for r in source.results if r["status"] == FAILED]
    badly_formed = [f"{r['paper']}.r{r['repeat']}" for r in folder.results
                    if r["status"] != FAILED and not pattern.match(r.get("weight_line") or "")]
    g1 = Gate(1, "every run exits 0 and starts with a Weight line", not failed and not badly_formed,
              "; ".join(failed + [f"{x} has no well-formed Weight line" for x in badly_formed]))
    missing = [f"{r['paper']}.r{r['repeat']} ({r['missing']})" for r in source.results
               if int(r.get("missing") or 0) > 0]
    g2 = Gate(2, "no run reports missing replies", not missing, "; ".join(missing))
    try:
        in_prompt = set(prompt_criteria(folder.prompt_text))
        graded = {g.criterion for g in cset.grades}
        extra, lacking = sorted(graded - in_prompt), sorted(in_prompt - graded)
        detail = "; ".join(x for x in (f"graded but not in CRITERIA: {extra}" if extra else "",
                                       f"in CRITERIA but not graded: {lacking}" if lacking else "") if x)
        g3 = Gate(3, "grades.csv criteria match the prompt's CRITERIA", not detail, detail)
    except PromptStructureError as error:
        g3 = Gate(3, "grades.csv criteria match the prompt's CRITERIA", False, str(error))
    broken = {name: m for name, m in run_parity(source).items() if m}
    g4 = Gate(4, "replay parity holds on every recorded run", not broken,
              "; ".join(f"{name}: {m[0]}" for name, m in sorted(broken.items())[:3]))
    return (g1, g2, g3, g4)


# --- readings --------------------------------------------------------------------


def reading_for(iv: metrics.Interval, improving: int) -> str:
    """`improving` is -1 when a smaller value is better, +1 when a larger one is."""
    if iv.low is None or iv.high is None:
        return NO_READING
    lo, hi = (iv.low, iv.high) if improving > 0 else (-iv.high, -iv.low)
    if lo > 0:
        return BETTER
    if hi < 0:
        return WORSE
    return WITHIN_NOISE


def reading_from_test(test: metrics.PermutationTest, improving: int,
                      level: float = metrics.SIGNIFICANCE) -> str:
    """`improving` is -1 when a smaller value is better, +1 when a larger one is."""
    if test.p is None or test.difference is None:
        return NO_READING
    if test.p >= level or test.difference == 0:
        return WITHIN_NOISE
    return BETTER if test.difference * improving > 0 else WORSE


def abs_bias(pw: Sequence[float], rev: Sequence[float]) -> float:
    return abs(metrics.bias(pw, rev))


def readings(cand: SplitScores, base: SplitScores) -> tuple[tuple[Reading, ...], tuple[str, ...]]:
    base_by = {p.paper: p for p in base.papers}
    pairs = [(p, base_by[p.paper]) for p in cand.papers if p.paper in base_by]
    papers = tuple(c.paper for c, _ in pairs)
    n = len(pairs)
    pw_c = [c.total for c, _ in pairs]
    pw_b = [b.total for _, b in pairs]
    rev = [c.reviewer_total for c, _ in pairs]
    if n == 0:
        return (), papers
    mae_iv = metrics.paired_difference(metrics.mae_stat(pw_c, rev), metrics.mae_stat(pw_b, rev), n)
    bias_iv = metrics.paired_difference(metrics.bias_stat(pw_c, rev), metrics.bias_stat(pw_b, rev), n)
    r_iv = metrics.paired_difference(metrics.pearson_stat(pw_c, rev), metrics.pearson_stat(pw_b, rev), n)
    mae_t = metrics.paired_permutation(metrics.mae, pw_c, pw_b, rev)
    bias_t = metrics.paired_permutation(abs_bias, pw_c, pw_b, rev)
    r_t = metrics.paired_permutation(metrics.pearson, pw_c, pw_b, rev)
    out = (
        Reading("MAE", metrics.mae(pw_b, rev), metrics.mae(pw_c, rev), mae_iv,
                reading_from_test(mae_t, -1), signed=False, p=mae_t.p),
        Reading("Bias", metrics.bias(pw_b, rev), metrics.bias(pw_c, rev), bias_iv,
                reading_from_test(bias_t, -1), signed=True, p=bias_t.p),
        Reading("Correlation", metrics.pearson(pw_b, rev), metrics.pearson(pw_c, rev), r_iv,
                reading_from_test(r_t, +1), signed=False, p=r_t.p),
    )
    return out, papers


def band_changes(cand: SplitScores, base: SplitScores) -> tuple[BandChange, ...]:
    base_by = {p.paper: p for p in base.papers}
    return tuple(BandChange(p.paper, base_by[p.paper].band, p.band, p.reviewer_band)
                 for p in cand.papers if p.paper in base_by and base_by[p.paper].band != p.band)


def compare(candidate: RunFolder, baseline: RunFolder | None, cset: CalibrationSet) -> Comparison:
    if baseline is not None:
        if baseline.synthetic != candidate.synthetic:
            raise CompareError("refusing to compare a synthetic run with a real one: "
                               f"candidate synthetic={candidate.synthetic}, baseline synthetic={baseline.synthetic}")
        if baseline.meta.get("model") != candidate.meta.get("model"):
            raise CompareError(f"the baseline ran on {baseline.meta.get('model')} and the candidate on "
                               f"{candidate.meta.get('model')}; compare against that model's baseline")
    found_gates = gates(candidate, cset)
    found: tuple[Reading, ...] = ()
    changes: tuple[BandChange, ...] = ()
    papers: tuple[str, ...] = ()
    cand_scores = base_scores = None
    if found_gates[2].passed:
        cand_scores = score_run(candidate, cset)
        base_scores = score_run(baseline, cset) if baseline is not None else None
        if CALIBRATION in cand_scores.splits:
            papers = tuple(p.paper for p in cand_scores.splits[CALIBRATION].papers)
        if base_scores is not None and CALIBRATION in cand_scores.splits and CALIBRATION in base_scores.splits:
            c, b = cand_scores.splits[CALIBRATION], base_scores.splits[CALIBRATION]
            found, papers = readings(c, b)
            changes = band_changes(c, b)
    return Comparison(candidate_run=candidate, baseline_run=baseline, candidate=cand_scores,
                      baseline=base_scores, gates=found_gates, readings=found,
                      band_changes=changes, papers=papers)


# --- the comment ------------------------------------------------------------------


def _p(r: Reading) -> str:
    return "" if r.p is None else f" (p {r.p:.2f})" if r.p >= 0.01 else " (p < 0.01)"


def _diff(r: Reading) -> str:
    iv = r.difference
    return f"{fmt(iv.estimate, True)} ({fmt(iv.low, True)} to {fmt(iv.high, True)})"


def render_comment(cmp: Comparison) -> str:
    meta = cmp.candidate_run.meta
    mode = "replay" if meta.get("mode") == REPLAY else "full run"
    n = len(cmp.papers)
    reps = meta.get("repeats")
    head = (f"### Paperweight calibration · {mode} · {n} paper{'' if n == 1 else 's'} × "
            f"{reps} repeat{'' if reps == 1 else 's'} · model {meta.get('model')}")
    if meta.get("partial"):
        head += " · partial (a subset of papers)"
    lines = [COMMENT_BANNER] if cmp.synthetic else []
    passed = sum(g.passed for g in cmp.gates)
    lines += [head, f"Gates: {passed} of {len(cmp.gates)} pass"]
    lines += [f"- Gate {g.number} fails, {g.name}: {g.detail}" for g in cmp.gates if not g.passed]
    lines.append("")
    if cmp.candidate is None:
        lines.append("No readings: the graded criteria do not match the prompt's CRITERIA (gate 3).")
        return "\n".join(lines) + "\n"
    if cmp.baseline_run is None:
        s = cmp.candidate.splits.get(CALIBRATION)
        lines.append(f"No baseline for model {meta.get('model')}: this run can serve as one.")
        if s is not None:
            lines += ["", "| Metric | Candidate (95% interval) |", "| --- | --- |",
                      f"| MAE | {fmt(s.mae.estimate)} ({fmt(s.mae.low)} to {fmt(s.mae.high)}) |",
                      f"| Bias | {fmt(s.bias.estimate, True)} ({fmt(s.bias.low, True)} to {fmt(s.bias.high, True)}) |",
                      f"| Correlation | {fmt(s.correlation.estimate)} ({fmt(s.correlation.low)} to "
                      f"{fmt(s.correlation.high)}) |"]
    else:
        lines += ["| Metric | Baseline | Candidate | Difference (95% interval) | Reading |",
                  "| --- | --- | --- | --- | --- |"]
        for r in cmp.readings:
            lines.append(f"| {r.metric} | {fmt(r.baseline, r.signed)} | {fmt(r.candidate, r.signed)} "
                         f"| {_diff(r)} | {r.reading}{_p(r)} |")
    lines.append("")
    if cmp.baseline_run is not None:
        changed = "; ".join(f"{b.paper} {b.baseline} to {b.candidate} (reviewers: {b.reviewers})"
                            for b in cmp.band_changes)
        lines.append(f"Bands changed: {changed or 'none'}")
    s = cmp.candidate.splits.get(CALIBRATION)
    if s is not None:
        st = s.stability
        lines.append(f"Stability: sigma {fmt(st.sigma)}, same band {st.same_band} of {st.pairs}, "
                     f"spans nested {st.spans_nested} of {st.pairs}")
    if cmp.candidate.triage_splits:
        lines.append(triage_line(cmp.candidate.triage_splits))
    hold = cmp.candidate.splits.get(HOLDOUT)
    if hold is not None:
        lines.append(f"Holdout ({len(hold.papers)} paper{"" if len(hold.papers) == 1 else "s"}, reported apart): bias {fmt(hold.bias.estimate, True)}, "
                     f"MAE {fmt(hold.mae.estimate)}, correlation {fmt(hold.correlation.estimate)}")
    if meta.get("mode") == REPLAY:
        lines.append(f"Replayed from {Path(meta['from_run']).name} with no model calls.")
    else:
        lines.append(f"Model calls: {meta.get('model_calls', 0)}.")
    return "\n".join(lines) + "\n"
