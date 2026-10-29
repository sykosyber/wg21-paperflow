# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The upstream proposal in docs/plans/calibration-harness-upstream.md applies
to the current prompt and does what it says, in the shim."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from calibrate import diagnostics, simulate
from calibrate import shim as shim_module


def proposal_hunk(repo_root: Path) -> tuple[str, str]:
    doc = (repo_root / "docs" / "plans" / "calibration-harness-upstream.md").read_text(encoding="utf-8")
    block = re.search(r"````diff\n(.*?)\n````\n", doc, re.S)
    assert block, "the proposal must carry its diff in a ````diff block"
    old, new = [], []
    lines = block.group(1).split("\n")
    # File headers come before the first hunk; after it, a removed Lua comment
    # line also starts with "---".
    first_hunk = next(i for i, line in enumerate(lines) if line.startswith("@@"))
    for line in lines[first_hunk:]:
        if line.startswith("@@"):
            continue
        # A blank context line may have lost its leading space in the document.
        tag, body = (line[:1], line[1:]) if line else (" ", "")
        if tag in (" ", "-"):
            old.append(body)
        if tag in (" ", "+"):
            new.append(body)
    return "\n".join(old), "\n".join(new)


@pytest.fixture(scope="module")
def upstream(repo_root: Path, prompt_text: str) -> str:
    old, new = proposal_hunk(repo_root)
    if prompt_text.count(old) != 1:
        pytest.skip("paperweight.md moved since the proposal was written; refresh its diff")
    return prompt_text.replace(old, new)


def run(prompt: str, ideal_paper, args: str) -> shim_module.ShimRun:
    grader = simulate.SimulatedGrader(simulate.PROFILES["noisy"], truth_seed=1, noise_seed=2)
    return shim_module.run_paper(prompt, ideal_paper("p4228r0"), grader, paper_id="P4228R0", args=args)


def test_without_the_argument_the_report_is_unchanged(upstream: str, prompt_text: str, ideal_paper) -> None:
    assert run(upstream, ideal_paper, "").report == run(prompt_text, ideal_paper, "").report


def test_with_the_argument_the_diagnostics_are_appended(upstream: str, ideal_paper) -> None:
    done = run(upstream, ideal_paper, "diagnostics")
    report = diagnostics.split_report(done.report)
    assert report.diagnostics_text == done.diagnostics
    assert diagnostics.parse_diagnostics(report.diagnostics_text).is_proposal


def test_only_the_analyze_epilogue_changes(upstream: str, prompt_text: str) -> None:
    before, after = shim_module.parse_prompt(prompt_text), shim_module.parse_prompt(upstream)
    for name in ("setup", "assess_prologue", "assess_epilogue", "grade_prologue",
                 "grade_epilogue", "analyze_prologue"):
        assert getattr(before, name).code == getattr(after, name).code
    assert before.analyze_epilogue.code != after.analyze_epilogue.code
