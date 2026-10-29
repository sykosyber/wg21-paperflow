# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Replay and the mode chooser."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from calibrate import aggregate, golden, replay, run, simulate

FIXED = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
PAPERS = ("P0533R9", "P1068R11", "P3953R0")


def clock() -> datetime:
    return FIXED


@pytest.fixture(scope="module")
def synthetic_set(package_root: Path, prompt_text: str) -> golden.CalibrationSet:
    return golden.load_for_prompt(package_root / "data" / "synthetic", prompt_text)


def shim_run(tmp_path: Path, prompt: str, cset, name: str) -> Path:
    path = tmp_path / f"{name}.md"
    path.write_bytes(prompt.encode("utf-8"))
    backend = run.ShimBackend(prompt_text=prompt, profile=simulate.PROFILES["noisy"], seed=3)
    config = run.RunConfig(prompt_path=path, repeats=2, jobs=2, papers=PAPERS, out=tmp_path / name)
    return run.full_run(config, backend, cset, now=clock)


# --- the mode chooser -------------------------------------------------------------------


def test_an_unchanged_prompt_replays(prompt_text: str) -> None:
    assert replay.choose_mode(prompt_text, prompt_text).mode == replay.REPLAY


@pytest.mark.parametrize("change", [
    {"INTER_RULE": "max"},
    {"LABELS": [(0, "Weightless"), (2, "Light"), (6, "Medium"), (10, "Heavy"), (14, "Supermassive")]},
    {"STRONG": 1.0, "CORROBORATION": 3},
    {"EDGE_WINDOW": 0.5},
    {"BINARY": []},
])
def test_tunable_changes_replay(prompt_text: str, change: dict) -> None:
    choice = replay.choose_mode(prompt_text, aggregate.patch_constants(prompt_text, **change))
    assert choice.mode == replay.REPLAY, choice.reason
    assert choice.changed_lines


def test_a_criterion_text_change_needs_a_full_run(prompt_text: str) -> None:
    old = '"Quantifies the usage or the size of the affected audience: counts, "'
    assert old in prompt_text
    cand = prompt_text.replace(old, '"Quantifies the usage or the size of the audience: counts, "')
    choice = replay.choose_mode(prompt_text, cand)
    assert choice.mode == replay.FULL
    assert "outside the Assess epilogue" in choice.reason


def test_a_grade_prose_change_needs_a_full_run(prompt_text: str) -> None:
    old = "Grade the text against that one criterion, and nothing else."
    assert old in prompt_text
    choice = replay.choose_mode(prompt_text, prompt_text.replace(old, old + " Be strict."))
    assert choice.mode == replay.FULL


def test_an_analyze_change_needs_a_full_run(prompt_text: str) -> None:
    old = "No lists, no headings, no detail dumps."
    assert old in prompt_text
    assert replay.choose_mode(prompt_text, prompt_text.replace(old, "No lists.")).mode == replay.FULL


def test_an_unmodelled_epilogue_change_needs_a_full_run(prompt_text: str) -> None:
    cand = prompt_text.replace("local QUOTE_WORDS = 40", "local QUOTE_WORDS = 30")
    choice = replay.choose_mode(prompt_text, cand)
    assert choice.mode == replay.FULL
    assert "does not model" in choice.reason and "QUOTE_WORDS" in choice.reason


def test_an_arithmetic_change_needs_a_full_run(prompt_text: str) -> None:
    old = "return (sorted[1] + sorted[2]) / 2"
    assert prompt_text.count(old) == 1
    cand = prompt_text.replace(old, "return (2 * sorted[1] + sorted[2]) / 3")
    assert replay.choose_mode(prompt_text, cand).mode == replay.FULL


def test_a_broken_layout_needs_a_full_run(prompt_text: str) -> None:
    cand = prompt_text.replace("### Grade\n", "### Grading\n", 1)
    choice = replay.choose_mode(prompt_text, cand)
    assert choice.mode == replay.FULL and "layout" in choice.reason


# --- replay ------------------------------------------------------------------------------


def test_replay_matches_a_full_run_of_the_candidate(tmp_path: Path, prompt_text: str, synthetic_set) -> None:
    """The simulated votes do not depend on the epilogue's tunables, so a full shim
    run of the candidate with the same seeds is what replay must reproduce."""
    candidate = aggregate.patch_constants(prompt_text, INTER_RULE="max")
    base = run.load_run(shim_run(tmp_path, prompt_text, synthetic_set, "base"))
    full = run.load_run(shim_run(tmp_path, candidate, synthetic_set, "cand"))
    replayed = run.load_run(replay.replay_run(base, candidate, tmp_path / "replayed", now=clock))
    assert replayed.meta["mode"] == "replay" and replayed.meta["model_calls"] == 0
    assert replayed.synthetic and replayed.meta["constants"]["INTER_RULE"] == "max"
    fields = ("weight_line", "span", "shown", "total_text", "totals_by_rule", "grades", "sample_totals")
    for r, f in zip(replayed.results, full.results):
        assert (r["paper"], r["repeat"]) == (f["paper"], f["repeat"])
        for key in fields:
            assert r[key] == f[key], (r["paper"], key)
    # The baseline's own Lua printed the max totals already, as a shadow.
    for r, b in zip(replayed.results, base.results):
        assert r["total_text"] == b["totals_by_rule"]["max"]


def test_replay_refuses_a_change_that_needs_a_full_run(tmp_path: Path, prompt_text: str, synthetic_set) -> None:
    base = run.load_run(shim_run(tmp_path, prompt_text, synthetic_set, "base"))
    cand = prompt_text.replace("local QUOTE_WORDS = 40", "local QUOTE_WORDS = 30")
    with pytest.raises(replay.ReplayError, match="a full run is needed"):
        replay.replay_run(base, cand, tmp_path / "r", now=clock)


def test_replay_refuses_when_parity_fails(tmp_path: Path, prompt_text: str, synthetic_set) -> None:
    folder = shim_run(tmp_path, prompt_text, synthetic_set, "base")
    diag = folder / "P0533R9.r1" / "diagnostics.md"
    text = diag.read_text(encoding="utf-8")
    line = next(x for x in text.split("\n") if x.startswith("Totals under every inter-section rule:"))
    tampered = line.replace("top2 ", "top2 1", 1)
    diag.write_text(text.replace(line, tampered), encoding="utf-8")
    with pytest.raises(replay.ReplayError, match="parity fails on 1 recorded runs, first P0533R9.r1"):
        replay.replay_run(run.load_run(folder), aggregate.patch_constants(prompt_text, INTER_RULE="max"),
                          tmp_path / "r", now=clock)


def test_replay_needs_a_full_run_as_source(tmp_path: Path, prompt_text: str, synthetic_set) -> None:
    base = run.load_run(shim_run(tmp_path, prompt_text, synthetic_set, "base"))
    once = run.load_run(replay.replay_run(base, prompt_text, tmp_path / "once", now=clock))
    with pytest.raises(replay.ReplayError, match="replay needs a full run"):
        replay.replay_run(once, prompt_text, tmp_path / "twice", now=clock)


def test_parity_holds_on_a_fresh_shim_run(tmp_path: Path, prompt_text: str, synthetic_set) -> None:
    folder = run.load_run(shim_run(tmp_path, prompt_text, synthetic_set, "base"))
    parity = replay.run_parity(folder)
    assert len(parity) == len(PAPERS) * 2
    assert all(m == [] for m in parity.values())


def test_the_replay_folder_records_its_source(tmp_path: Path, prompt_text: str, synthetic_set) -> None:
    base = shim_run(tmp_path, prompt_text, synthetic_set, "base")
    out = replay.replay_run(run.load_run(base), aggregate.patch_constants(prompt_text, INTER_RULE="max"),
                            tmp_path / "r", now=clock)
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["from_run"] == str(base)
    assert meta["from_prompt_sha256"] != meta["prompt_sha256"]
    assert meta["changed_lines"]
