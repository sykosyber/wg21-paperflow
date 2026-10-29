# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Parse paperweight's diagnostics.md and the report's verdict line.

The parser is strict: every line the Assess epilogue prints has one expected
shape, and anything else raises `DiagnosticsError`, so a change to the format
fails here instead of being half read. Printed numbers are kept as the exact
strings the Lua printed, beside their float values, so parity can be checked
to the character.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from calibrate.marking import strip_banner

APPENDIX_OPEN = "<!-- paperweight-diagnostics\n"
APPENDIX_CLOSE = "\n-->"

_PROVISIONAL_RE = re.compile(r"^Provisional: (?:n/a|(?P<label>.+?) \((?P<points>-?\d+\.\d\d)/(?P<max>\d+)(?P<edge>, close to .+)?\))$")
_COUNTS_RE = re.compile(
    r"^Provisionally addressed: (?P<met>\d+) of (?P<ncrit>\d+)\. Provisional points: "
    r"(?P<points>-?\d+\.\d\d) of (?P<max>\d+)\. Unsupported quotes rejected: (?P<rejected>\d+)\. "
    r"Replies missing: (?P<missing>\d+)\. Sections: (?P<sections>\d+)\. Samples: (?P<samples>\d+)\.$")
_RULE_RE = re.compile(
    r"^Intra-section rule: mean of (?P<samples>\d+) samples\. Inter-section rule in force: "
    r"(?P<rule>\S+) \(existence-asserting criteria always take the max\)\.$")
_TOTALS_PREFIX = "Totals under every inter-section rule: "
_PAIR_RE = re.compile(r"(\S+) (-?\d+\.\d\d)")
_AGREEMENT_RE = re.compile(
    r"^sample agreement: (?P<unanimous>\d+) of (?P<pairs>\d+) section-criterion pairs "
    r"unanimous \((?P<pct>\d+)%\)$")
_SINGLE_RE = re.compile(
    r"^single-sample totals would have been: (?P<totals>.*?)   "
    r"\(all (?P<samples>\d+) samples: (?P<points>-?\d+\.\d\d)\)$")
_CRITERION_RE = re.compile(
    r"^## (?P<short>\S+) - grade (?P<grade>-?\d+\.\d\d)(?P<binary>  \[binary: max\])? "
    r"\(fired in (?P<fired>\d+) of (?P<sections>\d+) sections, strong in (?P<strong>\d+)\)"
    r"(?P<threshold>  \(ON THRESHOLD\))?(?P<shared>  \(SHARED PASSAGE\))?$")
_UNDER_PREFIX = "under each rule: "
_VOTES_RE = re.compile(r"^  \[(?P<unit>\d+)\] (?P<title>.*) (?P<votes>\d+(?:/\d+)*)  -> (?P<mean>-?\d+\.\d\d)$")
_CANDIDATE_RE = re.compile(r"^candidate (?P<n>\d+) \(found by (?P<count>\d+) of (?P<passes>\d+) passes\): (?P<quote>.*)$")
_WEIGHT_RE = re.compile(r"^Weight: (?:n/a|(?P<span>.+?) \((?P<shown>-?\d+)/(?P<max>\d+)\))$")

NOT_PROPOSAL_LINE = "Classified as not a proposal; criteria not applied."


class DiagnosticsError(ValueError):
    """A diagnostics block or verdict line that does not have the printed shape."""


@dataclass(frozen=True)
class SectionVotes:
    unit: int
    title: str
    votes: tuple[int, ...]
    mean: str


@dataclass(frozen=True)
class Candidate:
    count: int
    passes: int
    quote: str


@dataclass(frozen=True)
class CriterionDiagnostics:
    short: str
    grade: str
    binary: bool
    fired: int
    sections: int
    strong: int
    on_threshold: bool
    shared_passage: bool
    under_rule: dict[str, str]
    votes: tuple[SectionVotes, ...]
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True)
class Diagnostics:
    """Everything diagnostics.md prints, as printed."""

    synthetic: bool
    is_proposal: bool
    provisional_line: str
    met: int = 0
    ncrit: int = 0
    points: str = ""
    max_points: int = 0
    rejected: int = 0
    missing: int = 0
    sections: int = 0
    samples: int = 0
    inter_rule: str = ""
    totals: dict[str, str] | None = None
    grades: dict[str, str] | None = None
    unanimous: int = 0
    pairs: int = 0
    single_sample_totals: tuple[str, ...] = ()
    headings: str = ""
    on_threshold: tuple[str, ...] = ()
    splits: tuple[str, ...] = ()
    criteria: tuple[CriterionDiagnostics, ...] = ()

    @property
    def shorts(self) -> tuple[str, ...]:
        return tuple(c.short for c in self.criteria)

    @property
    def model_calls(self) -> int:
        """The calls the run made: triage, Analyze, and one per Grade job."""
        if not self.is_proposal:
            return 2
        return 2 + self.ncrit * self.sections * self.samples

    def vote_grid(self) -> list[list[list[int]]]:
        """votes[c][k] is the list of sample votes, criteria and units in order."""
        return [[list(v.votes) for v in c.votes] for c in self.criteria]


@dataclass(frozen=True)
class WeightLine:
    line: str
    span: str
    shown: int | None
    max_points: int | None

    @property
    def applies(self) -> bool:
        return self.shown is not None

    def bands(self) -> tuple[str, ...]:
        """The band names the span covers, endpoints only."""
        if not self.span:
            return ()
        return tuple(self.span.split(" to "))


def parse_weight(line: str) -> WeightLine:
    m = _WEIGHT_RE.match(line)
    if not m:
        raise DiagnosticsError(f"not a Weight line: {line!r}")
    if m.group("span") is None:
        return WeightLine(line=line, span="", shown=None, max_points=None)
    return WeightLine(line=line, span=m.group("span"), shown=int(m.group("shown")),
                      max_points=int(m.group("max")))


@dataclass(frozen=True)
class Report:
    """A report.md split into its verdict line, prose and diagnostics."""

    synthetic: bool
    weight: WeightLine
    body: str
    diagnostics_text: str | None


def split_report(text: str) -> Report:
    """Splits a report that may carry the diagnostics appendix.

    The appendix is the block the restored epilogue writes:
    `<!-- paperweight-diagnostics` ... `-->`. The closing marker is taken from
    the end, because a quoted passage inside could itself contain `-->`.
    """
    synthetic, text = strip_banner(text)
    first, _, rest = text.partition("\n")
    weight = parse_weight(first.rstrip("\r"))
    open_at = rest.find(APPENDIX_OPEN)
    if open_at < 0:
        return Report(synthetic=synthetic, weight=weight, body=rest.strip("\n"), diagnostics_text=None)
    close_at = rest.rfind(APPENDIX_CLOSE)
    if close_at < open_at:
        raise DiagnosticsError("diagnostics appendix opens but never closes")
    diag = rest[open_at + len(APPENDIX_OPEN):close_at]
    return Report(synthetic=synthetic, weight=weight, body=rest[:open_at].strip("\n"),
                  diagnostics_text=diag)


def _pairs(text: str, what: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in re.split(r" {2,}", text.strip()):
        m = _PAIR_RE.fullmatch(chunk)
        if not m:
            raise DiagnosticsError(f"{what}: cannot read {chunk!r}")
        out[m.group(1)] = m.group(2)
    return out


class _Lines:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.i = 0

    def peek(self) -> str | None:
        return self.lines[self.i] if self.i < len(self.lines) else None

    def take(self) -> str:
        if self.i >= len(self.lines):
            raise DiagnosticsError("diagnostics end early")
        line = self.lines[self.i]
        self.i += 1
        return line

    def expect(self, literal: str) -> None:
        line = self.take()
        if line != literal:
            raise DiagnosticsError(f"line {self.i}: expected {literal!r}, found {line!r}")

    def match(self, pattern: re.Pattern[str]) -> re.Match[str]:
        line = self.take()
        m = pattern.match(line)
        if not m:
            raise DiagnosticsError(f"line {self.i}: unexpected {line!r}")
        return m


def parse_diagnostics(text: str) -> Diagnostics:
    """Parses diagnostics.md as the Assess epilogue writes it."""
    synthetic, text = strip_banner(text)
    lines = _Lines(text.replace("\r\n", "\n").split("\n"))
    lines.expect("# Diagnostics")
    lines.expect("")
    provisional = lines.take()
    if not _PROVISIONAL_RE.match(provisional):
        raise DiagnosticsError(f"unexpected provisional line {provisional!r}")
    lines.expect("")
    if provisional == "Provisional: n/a":
        lines.expect(NOT_PROPOSAL_LINE)
        _expect_end(lines)
        return Diagnostics(synthetic=synthetic, is_proposal=False, provisional_line=provisional)

    counts = lines.match(_COUNTS_RE)
    lines.expect("")
    rule = lines.match(_RULE_RE)
    totals_line = lines.take()
    if not totals_line.startswith(_TOTALS_PREFIX):
        raise DiagnosticsError(f"expected the totals line, found {totals_line!r}")
    totals = _pairs(totals_line[len(_TOTALS_PREFIX):], "totals")
    lines.expect("")
    lines.expect("## SUMMARY")
    grades_line = lines.take()
    if not grades_line.startswith("grades: "):
        raise DiagnosticsError(f"expected the grades line, found {grades_line!r}")
    grades = _pairs(grades_line[len("grades: "):], "grades")
    agreement = lines.match(_AGREEMENT_RE)
    single = lines.match(_SINGLE_RE)
    headings = ""
    if (lines.peek() or "").startswith("headings: "):
        headings = lines.take()[len("headings: "):].replace("   <- NOT h2, check the unit list", "")
    threshold_line = lines.take()
    if not threshold_line.startswith("on threshold: "):
        raise DiagnosticsError(f"expected the on-threshold line, found {threshold_line!r}")
    threshold = threshold_line[len("on threshold: "):]
    splits = _read_splits(lines)
    lines.expect("## END SUMMARY")
    lines.expect("")

    ncrit = int(counts.group("ncrit"))
    criteria = tuple(_read_criterion(lines) for _ in range(ncrit))
    _expect_end(lines)

    nsections = int(counts.group("sections"))
    for c in criteria:
        if len(c.votes) != nsections:
            raise DiagnosticsError(f"{c.short}: {len(c.votes)} units listed, {nsections} expected")
    return Diagnostics(
        synthetic=synthetic, is_proposal=True, provisional_line=provisional,
        met=int(counts.group("met")), ncrit=ncrit, points=counts.group("points"),
        max_points=int(counts.group("max")), rejected=int(counts.group("rejected")),
        missing=int(counts.group("missing")), sections=nsections,
        samples=int(counts.group("samples")), inter_rule=rule.group("rule"),
        totals=totals, grades=grades, unanimous=int(agreement.group("unanimous")),
        pairs=int(agreement.group("pairs")),
        single_sample_totals=tuple(t.strip() for t in single.group("totals").split(" / ")),
        headings=headings,
        on_threshold=() if threshold == "none" else tuple(threshold.split(", ")),
        splits=splits, criteria=criteria)


def _read_splits(lines: _Lines) -> tuple[str, ...]:
    first = lines.take()
    if first == "splits: none":
        return ()
    if not first.startswith("splits: "):
        raise DiagnosticsError(f"expected the splits line, found {first!r}")
    rows = [first[len("splits: "):]]
    while (lines.peek() or "").startswith("        "):
        rows.append(lines.take()[8:])
    return tuple(s for row in rows for s in row.split("  ") if s)


def _read_criterion(lines: _Lines) -> CriterionDiagnostics:
    head = lines.match(_CRITERION_RE)
    under = lines.take()
    if not under.startswith(_UNDER_PREFIX):
        raise DiagnosticsError(f"expected the per-rule line, found {under!r}")
    lines.expect("votes by section:")
    votes = []
    while (lines.peek() or "").startswith("  ["):
        m = lines.match(_VOTES_RE)
        votes.append(SectionVotes(unit=int(m.group("unit")), title=m.group("title").rstrip(),
                                  votes=tuple(int(v) for v in m.group("votes").split("/")),
                                  mean=m.group("mean")))
    candidates = []
    if lines.peek() == "candidates: (none validated)":
        lines.take()
    else:
        while (lines.peek() or "").startswith("candidate "):
            m = lines.match(_CANDIDATE_RE)
            candidates.append(Candidate(count=int(m.group("count")),
                                        passes=int(m.group("passes")), quote=m.group("quote")))
        if not candidates:
            raise DiagnosticsError(f"{head.group('short')}: no candidate lines")
    lines.expect("")
    return CriterionDiagnostics(
        short=head.group("short"), grade=head.group("grade"), binary=bool(head.group("binary")),
        fired=int(head.group("fired")), sections=int(head.group("sections")),
        strong=int(head.group("strong")), on_threshold=bool(head.group("threshold")),
        shared_passage=bool(head.group("shared")),
        under_rule=_pairs(under[len(_UNDER_PREFIX):], "per-rule grades"),
        votes=tuple(votes), candidates=tuple(candidates))


def _expect_end(lines: _Lines) -> None:
    rest = lines.lines[lines.i:]
    if any(line.strip() for line in rest):
        raise DiagnosticsError(f"unexpected trailing text: {rest[0]!r}")
