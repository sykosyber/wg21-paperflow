# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Replay a recorded full run under a candidate prompt, and choose the mode.

Replay recomputes every criterion grade, the totals, the provisional line and
the verdict line from the per-section votes in a full run's diagnostics, with
no model call. It answers "what would this aggregation change have done to the
last full run?".

`choose_mode` diffs the candidate prompt against the run's prompt. Replay is
offered only when every changed line sits inside the Assess epilogue's Lua
block in both prompts, and the epilogues differ only in the tunables
`aggregate.py` models. Anything else changes the votes themselves, or changes
the arithmetic in a way the Python copy does not follow, so it needs a full
run. Before replaying, the source run must pass parity: the Python arithmetic
under the source's own constants must reproduce every number its Lua printed.
If it does not, replay refuses rather than report a wrong number.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from calibrate import __version__, aggregate, diagnostics, shim, synthetic
from calibrate.run import FAILED, RunFolder, write_json

REPLAY, FULL = "replay", "full"


class ReplayError(RuntimeError):
    """Replay is not possible: the change needs a full run, or parity fails."""


@dataclass(frozen=True)
class ModeChoice:
    mode: str
    reason: str
    changed_lines: tuple[int, ...] = ()


def choose_mode(baseline_prompt: str, candidate_prompt: str) -> ModeChoice:
    """Replay when the change is confined to what the epilogue's arithmetic models."""
    base = baseline_prompt.replace("\r\n", "\n")
    cand = candidate_prompt.replace("\r\n", "\n")
    try:
        base_epi = shim.parse_prompt(base).assess_epilogue
        cand_epi = shim.parse_prompt(cand).assess_epilogue
    except shim.PromptStructureError as error:
        return ModeChoice(FULL, f"the prompt's layout changed: {error}")
    matcher = difflib.SequenceMatcher(a=base.split("\n"), b=cand.split("\n"), autojunk=False)
    changes = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    if not changes:
        return ModeChoice(REPLAY, "the prompt is unchanged")
    lines: list[int] = []
    for _, i1, i2, j1, j2 in changes:
        lines.extend(range(j1 + 1, max(j2, j1 + 1) + 1) if j2 > j1 else [j1 + 1])
        if not (_inside(i1, i2, base_epi) and _inside(j1, j2, cand_epi)):
            return ModeChoice(FULL, f"line {j1 + 1} of the candidate changes outside the "
                              "Assess epilogue's Lua block, so the votes themselves may change",
                              tuple(sorted(set(lines))))
    unmodelled = aggregate.unmodelled_changes(base_epi.code, cand_epi.code)
    if unmodelled:
        return ModeChoice(FULL, "the Assess epilogue changes in a way replay does not model: "
                          + "; ".join(unmodelled[:4]), tuple(sorted(set(lines))))
    try:
        aggregate.EpilogueConstants.from_epilogue(cand_epi.code)
    except aggregate.EpilogueError as error:
        return ModeChoice(FULL, f"the candidate's tunables cannot be read: {error}")
    return ModeChoice(REPLAY, "only the Assess epilogue's tunables change", tuple(sorted(set(lines))))


def _inside(lo: int, hi: int, block: shim.LuaBlock) -> bool:
    """Lines [lo, hi), 0-based, fall inside the block's code (an insertion may sit at its end)."""
    first, last = block.first_line - 1, block.last_line
    if lo == hi:
        return first <= lo <= last
    return first <= lo and hi <= last


def parity_mismatches(d: diagnostics.Diagnostics, weight: diagnostics.WeightLine,
                      k: aggregate.EpilogueConstants) -> list[str]:
    """Where the Python arithmetic disagrees with what the Lua printed, if anywhere."""
    if not d.is_proposal:
        return [] if weight.line == "Weight: n/a" else [f"verdict {weight.line!r} on a non-proposal"]
    a = aggregate.aggregate(d.shorts, d.vote_grid(), d.samples, k)
    out = []
    if d.inter_rule != k.inter_rule:
        out.append(f"rule in force {d.inter_rule}, constants say {k.inter_rule}")
    printed = d.totals or {}
    for r in aggregate.RULES:
        if f"{a.shadow_points[r]:.2f}" != printed.get(r):
            out.append(f"total under {r}: {a.shadow_points[r]:.2f} against {printed.get(r)}")
    for c, score in zip(d.criteria, a.scores):
        if f"{score:.2f}" != c.grade:
            out.append(f"{c.short}: {score:.2f} against {c.grade}")
    if a.provisional_line != d.provisional_line:
        out.append(f"provisional line {a.provisional_line!r} against {d.provisional_line!r}")
    if tuple(f"{t:.2f}" for t in a.sample_totals) != d.single_sample_totals:
        out.append("single-sample totals differ")
    if a.weight_line != weight.line:
        out.append(f"verdict {a.weight_line!r} against {weight.line!r}")
    return out


def run_parity(folder: RunFolder) -> dict[str, list[str]]:
    """Parity on every completed run of a full run folder, keyed by `<paper>.r<n>`."""
    k = folder.constants
    out = {}
    for r in folder.results:
        if r["status"] == FAILED:
            continue
        path = folder.run_path(r["paper"], r["repeat"])
        report = diagnostics.split_report((path / "report.md").read_bytes().decode("utf-8"))
        d = diagnostics.parse_diagnostics((path / "diagnostics.md").read_bytes().decode("utf-8"))
        out[path.name] = parity_mismatches(d, report.weight, k)
    return out


def replay_run(source: RunFolder, candidate_prompt: str, out: Path, *,
               now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> Path:
    """Re-aggregates a full run under the candidate prompt and writes a replay run folder."""
    if source.meta.get("mode") != FULL:
        raise ReplayError(f"{source.path} is a {source.meta.get('mode')} run; replay needs a full run")
    candidate = candidate_prompt.replace("\r\n", "\n")
    choice = choose_mode(source.prompt_text, candidate)
    if choice.mode != REPLAY:
        raise ReplayError(f"a full run is needed: {choice.reason}")
    broken = {name: m for name, m in run_parity(source).items() if m}
    if broken:
        name, mismatches = sorted(broken.items())[0]
        raise ReplayError(f"parity fails on {len(broken)} recorded runs, first {name}: "
                          f"{mismatches[0]}; refusing to replay")
    k = aggregate.EpilogueConstants.from_prompt(candidate)
    out.mkdir(parents=True, exist_ok=False)
    (out / "prompt.md").write_bytes(candidate.encode("utf-8"))
    for r in source.results:
        folder = out / f"{r['paper']}.r{r['repeat']}"
        folder.mkdir()
        write_json(folder / "result.json", _replayed(source, r, k))
    meta = {
        key: source.meta[key] for key in ("synthetic", "model", "repeats", "papers", "partial",
                                          "splits", "set") if key in source.meta
    }
    meta.update({
        "mode": REPLAY, "backend": "replay", "harness_version": __version__,
        "from_run": str(source.path), "from_prompt_sha256": source.meta.get("prompt_sha256"),
        "from_backend": source.meta.get("backend"),
        "prompt_sha256": synthetic.prompt_sha256(candidate), "constants": k.to_dict(),
        "mode_reason": choice.reason, "changed_lines": list(choice.changed_lines),
        "created_at": now().isoformat(timespec="seconds"), "status": "done",
        "runs": len(source.results), "model_calls": 0,
        "runs_failed": sum(r["status"] == FAILED for r in source.results),
        "runs_incomplete": sum(r["status"] == "incomplete" for r in source.results),
    })
    write_json(out / "meta.json", meta)
    return out


def _replayed(source: RunFolder, r: dict, k: aggregate.EpilogueConstants) -> dict:
    keep = ("paper", "repeat", "synthetic", "status", "exit_code", "error", "is_proposal",
            "unanimous", "pairs", "rejected", "missing", "sections", "samples")
    result = {key: r[key] for key in keep if key in r}
    result["replayed_from"] = f"{r['paper']}.r{r['repeat']}"
    result["model_calls"] = 0
    if r["status"] == FAILED or not r.get("is_proposal"):
        for key in ("weight_line", "span", "shown", "total", "grades"):
            if key in r:
                result[key] = r[key]
        return result
    path = source.run_path(r["paper"], r["repeat"])
    d = diagnostics.parse_diagnostics((path / "diagnostics.md").read_bytes().decode("utf-8"))
    a = aggregate.aggregate(d.shorts, d.vote_grid(), d.samples, k)
    weight = diagnostics.parse_weight(a.weight_line)
    # Numbers are kept as the Lua would print them, as a full run records them.
    result.update({
        "weight_line": a.weight_line, "span": a.span, "shown": weight.shown,
        "total": float(f"{a.points:.2f}"), "total_text": f"{a.points:.2f}", "inter_rule": k.inter_rule,
        "totals_by_rule": {rule: f"{a.shadow_points[rule]:.2f}" for rule in aggregate.RULES},
        "grades": {s: float(f"{g:.2f}") for s, g in zip(a.shorts, a.scores)},
        "sample_totals": [f"{t:.2f}" for t in a.sample_totals],
        "provisional_line": a.provisional_line,
    })
    return result


def load_prompt(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")
