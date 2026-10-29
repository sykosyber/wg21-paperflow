# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Score one run folder against a calibration set, and render its summary.

A paper's paperweight total is the mean of its completed repeats (status ok);
a paper with no completed repeat, or triaged NOT_PROPOSAL, is left out of the
agreement metrics and counted. Bands use the run's own LABELS and the
epilogue's rounding. The calibration and holdout splits are scored
separately: every number on the calibration papers is in-sample.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from calibrate import aggregate, metrics
from calibrate.golden import CalibrationSet
from calibrate.marking import SYNTHETIC
from calibrate.run import FAILED, INCOMPLETE, OK, RunFolder

SYNTHETIC_SUMMARY_BANNER = (
    f"{SYNTHETIC}: built from synthetic grades or the shim backend; "
    "no number here is a finding about paperweight."
)


@dataclass(frozen=True)
class PaperScore:
    paper: str
    split: str
    completed: int
    total: float
    grades: dict[str, float]
    band: str
    totals: tuple[float, ...]
    bands: tuple[str, ...]
    spans: tuple[tuple[int, int], ...]
    repeat_grades: tuple[dict[str, float], ...]
    reviewer_total: float
    reviewer_grades: dict[str, float]
    reviewer_band: str
    reviewer_totals: tuple[float, ...]


@dataclass(frozen=True)
class SplitScores:
    """Agreement and stability on one split."""

    split: str
    papers: tuple[PaperScore, ...]
    bias: metrics.Interval
    mae: metrics.Interval
    correlation: metrics.Interval
    ceiling: metrics.Interval
    criterion_bias: dict[str, metrics.Interval]
    grade2: dict[str, tuple[int, int, int, int]]
    band_agreement: tuple[int, int]
    stability: metrics.Stability


@dataclass(frozen=True)
class RunScores:
    run: RunFolder
    splits: dict[str, SplitScores]
    excluded: dict[str, str]
    health: dict[str, float | int]
    # Papers whose completed repeats disagree on whether they are proposals:
    # paper -> (repeats triaged NOT_PROPOSAL, completed repeats).
    triage_splits: dict[str, tuple[int, int]]

    @property
    def synthetic(self) -> bool:
        return self.run.synthetic


def paper_scores(folder: RunFolder, cset: CalibrationSet) -> tuple[list[PaperScore], dict[str, str]]:
    k = folder.constants
    out, excluded = [], {}
    by_paper = folder.by_paper()
    for entry in cset.papers:
        runs = by_paper.get(entry.paper)
        if runs is None:
            continue
        done = [r for r in runs if r["status"] == OK]
        if not done:
            excluded[entry.paper] = "no completed run"
            continue
        refused = sum(1 for r in done if not r.get("is_proposal"))
        if refused:
            excluded[entry.paper] = ("triaged NOT_PROPOSAL" if refused == len(done) else
                                     f"triage disagreed across repeats: {refused} of {len(done)} "
                                     "called it not a proposal")
            continue
        totals = tuple(float(r["total"]) for r in done)
        total = metrics.mean(totals)
        grades = {c: metrics.mean([float(r["grades"][c]) for r in done]) for c in cset.criteria}
        rev_total = cset.reviewer_mean_total(entry.paper)
        out.append(PaperScore(
            paper=entry.paper, split=entry.split, completed=len(done), total=total, grades=grades,
            band=k.label_for(aggregate.lua_round(total)), totals=totals,
            bands=tuple(k.label_for(aggregate.lua_round(t)) for t in totals),
            spans=tuple(k.span_indices(r["span"]) for r in done),
            repeat_grades=tuple({c: float(r["grades"][c]) for c in cset.criteria} for r in done),
            reviewer_total=rev_total, reviewer_grades=cset.reviewer_means(entry.paper),
            reviewer_band=k.label_for(aggregate.lua_round(rev_total)),
            reviewer_totals=tuple(float(cset.reviewer_total(entry.paper, r)) for r in cset.reviewers)))
    return out, excluded


def split_scores(split: str, papers: list[PaperScore], cset: CalibrationSet) -> SplitScores:
    n = len(papers)
    pw = [p.total for p in papers]
    rev = [p.reviewer_total for p in papers]
    per_reviewer = [[p.reviewer_totals[i] for p in papers] for i in range(len(cset.reviewers))]
    pw_g = [p.grades for p in papers]
    rev_g = [p.reviewer_grades for p in papers]
    grade2 = {}
    for c in cset.criteria:
        # One judgement per completed repeat, as the reviewers give one each.
        pw_k, pw_n = metrics.grade2_count([g[c] for p in papers for g in p.repeat_grades])
        rv = [cset.grade(p.paper, r, c) for p in papers for r in cset.reviewers]
        grade2[c] = (pw_k, pw_n, sum(1 for g in rv if g == metrics.FULL_MARKS), len(rv))
    return SplitScores(
        split=split, papers=tuple(papers),
        bias=metrics.bootstrap(metrics.bias_stat(pw, rev), n),
        mae=metrics.bootstrap(metrics.mae_stat(pw, rev), n),
        correlation=metrics.bootstrap(metrics.pearson_stat(pw, rev), n),
        ceiling=metrics.bootstrap(metrics.ceiling_stat(per_reviewer), n),
        criterion_bias={c: metrics.bootstrap(metrics.criterion_bias_stat(pw_g, rev_g, c), n)
                        for c in cset.criteria},
        grade2=grade2,
        band_agreement=metrics.band_agreement([p.band for p in papers], [p.reviewer_band for p in papers]),
        stability=metrics.stability([list(zip(p.totals, p.bands, p.spans)) for p in papers]))


def score_run(folder: RunFolder, cset: CalibrationSet) -> RunScores:
    if cset.synthetic and not folder.synthetic:
        raise ValueError("a run scored on synthetic grades must itself be marked synthetic")
    papers, excluded = paper_scores(folder, cset)
    by_split: dict[str, list[PaperScore]] = {}
    for p in papers:
        by_split.setdefault(p.split, []).append(p)
    splits = {s: split_scores(s, ps, cset) for s, ps in sorted(by_split.items())}
    results = folder.results
    health = {
        "runs": len(results),
        "runs_failed": sum(r["status"] == FAILED for r in results),
        "runs_incomplete": sum(r["status"] == INCOMPLETE for r in results),
        "replies_missing": sum(int(r.get("missing") or 0) for r in results),
        "quotes_rejected": sum(int(r.get("rejected") or 0) for r in results),
        "not_proposal": sum(1 for r in results if r["status"] == OK and r.get("is_proposal") is False),
        "model_calls": int(folder.meta.get("model_calls") or 0),
        "wall_seconds": float(folder.meta.get("wall_seconds") or 0.0),
    }
    unanimous = sum(int(r.get("unanimous") or 0) for r in results if r["status"] == OK)
    pairs = sum(int(r.get("pairs") or 0) for r in results if r["status"] == OK)
    health["sample_agreement"] = round(unanimous / pairs, 4) if pairs else 0.0
    splits_triage = triage_splits(folder)
    health["triage_disagreements"] = len(splits_triage)
    return RunScores(run=folder, splits=splits, excluded=excluded, health=health,
                     triage_splits=splits_triage)


def triage_splits(folder: RunFolder) -> dict[str, tuple[int, int]]:
    """Papers whose completed repeats disagree on being proposals.

    Flagged, never gated: like span nesting it is a sampled property, so a gate
    on it would fail at random. A flip turns a full verdict into `Weight: n/a`.
    """
    out = {}
    for paper, runs in folder.by_paper().items():
        done = [r for r in runs if r["status"] == OK]
        refused = sum(1 for r in done if r.get("is_proposal") is False)
        if 0 < refused < len(done):
            out[paper] = (refused, len(done))
    return out


def triage_line(splits: dict[str, tuple[int, int]]) -> str:
    return "Triage disagreed across repeats: " + "; ".join(
        f"{p} ({k} of {n} called it not a proposal)" for p, (k, n) in sorted(splits.items()))


# --- rendering ------------------------------------------------------------------


def fmt(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.2f}" if signed else f"{x:.2f}"


def fmt_interval(iv: metrics.Interval, signed: bool = False) -> str:
    return f"{fmt(iv.estimate, signed)} ({fmt(iv.low, signed)} to {fmt(iv.high, signed)})"


def summary_json(scores: RunScores) -> dict:
    def iv(i: metrics.Interval) -> dict:
        return {"estimate": i.estimate, "low": i.low, "high": i.high, "used": i.used, "dropped": i.dropped}
    meta = scores.run.meta
    out: dict = {
        "synthetic": scores.synthetic, "run": str(scores.run.path), "mode": meta.get("mode"),
        "model": meta.get("model"), "prompt_sha256": meta.get("prompt_sha256"),
        "repeats": meta.get("repeats"), "partial": meta.get("partial", False),
        "excluded": scores.excluded, "health": scores.health,
        "triage_splits": {p: {"not_proposal": k, "completed": n} for p, (k, n) in scores.triage_splits.items()},
        "splits": {},
    }
    for name, s in scores.splits.items():
        st = s.stability
        out["splits"][name] = {
            "papers": [{"paper": p.paper, "total": p.total, "band": p.band, "reviewer_total": p.reviewer_total,
                        "reviewer_band": p.reviewer_band, "completed": p.completed} for p in s.papers],
            "bias": iv(s.bias), "mae": iv(s.mae), "correlation": iv(s.correlation),
            "reviewer_ceiling": iv(s.ceiling),
            "criterion_bias": {c: iv(i) for c, i in s.criterion_bias.items()},
            "grade2": {c: {"paperweight": [a, b], "reviewers": [c2, d]} for c, (a, b, c2, d) in s.grade2.items()},
            "band_agreement": list(s.band_agreement),
            "stability": {"sigma": st.sigma, "pairs": st.pairs, "same_exact": st.same_exact,
                          "same_integer": st.same_integer, "same_band": st.same_band,
                          "spans_nested": st.spans_nested, "papers": st.papers},
        }
    return out


def summary_markdown(scores: RunScores) -> str:
    meta = scores.run.meta
    lines = []
    if scores.synthetic:
        lines.append(SYNTHETIC_SUMMARY_BANNER)
    lines += [f"# Calibration run: {scores.run.path.name}", "",
              f"Mode {meta.get('mode')} · model {meta.get('model')} · repeats {meta.get('repeats')} · "
              f"prompt {str(meta.get('prompt_sha256'))[:12]}"
              + (" · partial (a subset of papers)" if meta.get("partial") else ""), ""]
    for name, s in scores.splits.items():
        st = s.stability
        lines += [f"## {name.capitalize()} ({len(s.papers)} papers)", "",
                  "| Metric | Value (95% interval) |", "| --- | --- |",
                  f"| Bias | {fmt_interval(s.bias, signed=True)} |",
                  f"| MAE | {fmt_interval(s.mae)} |",
                  f"| Correlation | {fmt_interval(s.correlation)} |",
                  f"| Reviewer ceiling | {fmt_interval(s.ceiling)} |",
                  f"| Band agreement | {s.band_agreement[0]} of {s.band_agreement[1]} |", "",
                  "| Criterion | Bias (95% interval) | Grade 2, paperweight | Grade 2, reviewers |",
                  "| --- | --- | --- | --- |"]
        for c, iv in s.criterion_bias.items():
            a, b, c2, d = s.grade2[c]
            lines.append(f"| {c} | {fmt_interval(iv, signed=True)} | {a} of {b} | {c2} of {d} |")
        lines += ["", f"Stability: sigma {fmt(st.sigma)}, same exact {st.same_exact} of {st.pairs}, "
                      f"same integer {st.same_integer} of {st.pairs}, same band {st.same_band} of {st.pairs}, "
                      f"spans nested {st.spans_nested} of {st.pairs}", "",
                  "| Paper | Total | Band | Reviewers | Reviewers' band |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {p.paper} | {p.total:.2f} | {p.band} | {p.reviewer_total:.2f} | {p.reviewer_band} |"
                  for p in s.papers]
        lines.append("")
    h = scores.health
    lines += ["## Health", "",
              f"Runs {h['runs']}, failed {h['runs_failed']}, incomplete {h['runs_incomplete']}, "
              f"replies missing {h['replies_missing']}, quotes rejected {h['quotes_rejected']}, "
              f"NOT_PROPOSAL {h['not_proposal']}, triage disagreements {h['triage_disagreements']}, "
              f"model calls {h['model_calls']}, "
              f"wall time {h['wall_seconds']:.1f}s, sample agreement {h['sample_agreement']:.0%}."]
    if scores.triage_splits:
        lines += ["", triage_line(scores.triage_splits)]
    if scores.excluded:
        lines += ["", "Left out: " + ", ".join(f"{p} ({why})" for p, why in sorted(scores.excluded.items()))]
    return "\n".join(lines) + "\n"


def write_summary(scores: RunScores) -> None:
    folder = scores.run.path
    (folder / "summary.json").write_bytes(
        (json.dumps(summary_json(scores), indent=2, sort_keys=True) + "\n").encode("utf-8"))
    (folder / "summary.md").write_bytes(summary_markdown(scores).encode("utf-8"))
