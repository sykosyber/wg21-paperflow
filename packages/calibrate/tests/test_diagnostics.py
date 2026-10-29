# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The diagnostics parser: what it reads, and that it refuses what it cannot."""

from __future__ import annotations

from pathlib import Path

import pytest

from calibrate import diagnostics

PARITY = Path(__file__).parent / "fixtures" / "synthetic" / "parity"


def fixture(prefix: str, kind: str) -> str:
    path = next(PARITY.glob(f"{prefix}-*.{kind}.md"))
    return path.read_text(encoding="utf-8")


def test_a_proposal_parses_completely() -> None:
    d = diagnostics.parse_diagnostics(fixture("01", "diagnostics"))
    assert d.synthetic and d.is_proposal
    assert d.shorts == ("motivation", "audience", "prior_art", "vehicle", "coordination",
                        "insufficiency", "implementation")
    assert d.samples == 3 and d.sections >= 4
    assert set(d.totals or {}) == {"top2", "corroborated", "accumulate", "max"}
    grid = d.vote_grid()
    assert len(grid) == 7 and all(len(row) == d.sections for row in grid)
    assert all(len(cell) == 3 for row in grid for cell in row)
    assert d.criteria[-1].binary and not d.criteria[0].binary
    assert d.model_calls == 2 + 7 * d.sections * 3


def test_a_report_splits_into_weight_and_body() -> None:
    report = diagnostics.split_report(fixture("01", "report"))
    assert report.synthetic
    assert report.weight.applies and report.weight.max_points == 14
    assert report.diagnostics_text is None
    assert report.body.startswith("SYNTHETIC prose")


def test_the_appendix_is_read_from_a_report() -> None:
    diag = fixture("01", "diagnostics").split("\n", 1)[1]
    quote_with_marker = diag.replace("candidate 1 (found by", "candidate 1 (found by", 1)
    text = ("Weight: Medium (6/14)\n\nProse.\n\n<!-- paperweight-diagnostics\n"
            + quote_with_marker + " --> inside a quote\n-->\n\n")
    report = diagnostics.split_report(text)
    assert not report.synthetic
    assert report.body == "Prose."
    assert report.diagnostics_text is not None
    assert report.diagnostics_text.endswith("--> inside a quote")


@pytest.mark.parametrize(("line", "span", "shown"), [
    ("Weight: Medium (6/14)", "Medium", 6),
    ("Weight: Light to Heavy (7/14)", "Light to Heavy", 7),
    ("Weight: n/a", "", None),
])
def test_weight_lines(line: str, span: str, shown: int | None) -> None:
    w = diagnostics.parse_weight(line)
    assert (w.span, w.shown) == (span, shown)


@pytest.mark.parametrize("line", ["Weight: Medium", "Verdict: Medium (6/14)", "Weight: Medium (6.5/14)", ""])
def test_bad_weight_lines_raise(line: str) -> None:
    with pytest.raises(diagnostics.DiagnosticsError):
        diagnostics.parse_weight(line)


@pytest.mark.parametrize(("old", "new"), [
    ("Unsupported quotes rejected:", "Unsupported quote rejected:"),
    ("Totals under every inter-section rule: ", "Totals under each rule: "),
    ("## END SUMMARY", "## FIN"),
    ("votes by section:", "votes per section:"),
])
def test_format_changes_raise(old: str, new: str) -> None:
    text = fixture("01", "diagnostics")
    assert old in text
    with pytest.raises(diagnostics.DiagnosticsError):
        diagnostics.parse_diagnostics(text.replace(old, new, 1))


def test_a_truncated_block_raises() -> None:
    text = fixture("01", "diagnostics")
    with pytest.raises(diagnostics.DiagnosticsError):
        diagnostics.parse_diagnostics(text[: len(text) // 2])


def test_not_a_proposal() -> None:
    text = next(PARITY.glob("*-N5040-*.diagnostics.md")).read_text(encoding="utf-8")
    d = diagnostics.parse_diagnostics(text)
    assert not d.is_proposal and d.model_calls == 2
