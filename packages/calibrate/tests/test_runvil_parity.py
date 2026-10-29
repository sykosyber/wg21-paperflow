# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The harness against runs of the real engine, not just its shim."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from calibrate import aggregate, diagnostics, replay, shim, synthetic

RUNVIL = Path(__file__).parent / "fixtures" / "runvil"
SET_PAPERS = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "papers"
INDEX = [json.loads(line) for line in (RUNVIL / "index.jsonl").read_text(encoding="utf-8").splitlines()]
TITLE_WIDTH = 44


def load(row: dict) -> tuple[diagnostics.Report, diagnostics.Diagnostics]:
    report = diagnostics.split_report((RUNVIL / f"{row['name']}.report.md").read_bytes().decode("utf-8"))
    diag_text = (RUNVIL / f"{row['name']}.diagnostics.md").read_bytes().decode("utf-8")
    assert report.diagnostics_text == diag_text
    return report, diagnostics.parse_diagnostics(diag_text)


@pytest.mark.parametrize("row", INDEX, ids=[r["name"] for r in INDEX])
def test_the_real_runs_are_not_synthetic(row: dict) -> None:
    report, d = load(row)
    assert row["synthetic"] is False
    assert not report.synthetic and not d.synthetic
    assert d.missing == 0 and d.model_calls == row["model_calls"]


@pytest.mark.parametrize("row", INDEX, ids=[r["name"] for r in INDEX])
def test_parity_with_the_real_lua(row: dict) -> None:
    report, d = load(row)
    k = aggregate.EpilogueConstants.from_dict(row["constants"])
    assert replay.parity_mismatches(d, report.weight, k) == []


@pytest.mark.parametrize("row", INDEX, ids=[r["name"] for r in INDEX])
def test_the_shim_sections_the_paper_as_the_engine_did(row: dict, prompt_text: str) -> None:
    if synthetic.prompt_sha256(prompt_text) != row["prompt_sha256"]:
        pytest.skip("paperweight.md changed since this run was recorded")
    paper = (SET_PAPERS / f"{row['paper']}.md").read_bytes()
    assert hashlib.sha256(paper).hexdigest() == row["paper_sha256"]
    _, d = load(row)
    split = shim.split_paper(prompt_text, paper.decode("utf-8"))

    def shown(title: str) -> str:
        # diagnostics.md cuts a long title to 41 bytes and "..."
        return title if len(title.encode()) <= TITLE_WIDTH else title.encode()[:41].decode(errors="ignore") + "..."

    assert [v.title for v in d.criteria[0].votes] == [shown(t) for t in split.titles]
    assert d.shorts == split.shorts and d.samples == split.samples
    assert d.headings == split.heading_style
