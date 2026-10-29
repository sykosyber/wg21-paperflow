# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Load and validate a calibration set: papers.jsonl, papers/ and grades.csv.

One loader reads both the real golden set (`data/golden/`) and the synthetic
one (`data/synthetic/`), and it refuses to let them meet:

- A set is synthetic when its files say so: `"synthetic": true` on every
  papers.jsonl line, and a first line starting with SYNTHETIC in grades.csv
  and README.md. Every file of a set must agree, or the set is refused.
- A synthetic set under a directory named `golden`, or an unmarked set under
  one named `synthetic`, is refused.

Checks: the schema of every line and row; each paper's markdown against its
pinned sha256; grades in 0, 1, 2; exactly one grade per paper, reviewer and
criterion; and the graded criteria against the prompt's CRITERIA table in
both directions, so renaming a criterion fails loudly instead of silently
dropping its grades.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from calibrate.marking import is_synthetic_text
from calibrate.shim import prompt_criteria

GRADE_VALUES = ("0", "1", "2")
SPLITS = ("calibration", "holdout")
PAPER_FIELDS = ("paper", "markdown_sha256", "tomd_version", "split")
GRADE_COLUMNS = ["paper", "reviewer", "criterion", "grade"]


class SetError(ValueError):
    """A calibration set that fails validation."""


@dataclass(frozen=True)
class PaperEntry:
    paper: str
    markdown_sha256: str
    tomd_version: str
    split: str
    path: Path

    def text(self) -> str:
        return self.path.read_bytes().decode("utf-8")


@dataclass(frozen=True)
class Grade:
    paper: str
    reviewer: str
    criterion: str
    grade: int


@dataclass(frozen=True)
class CalibrationSet:
    """A validated set, with the per-paper reviewer views the metrics need."""

    root: Path
    synthetic: bool
    papers: tuple[PaperEntry, ...]
    grades: tuple[Grade, ...]
    reviewers: tuple[str, ...]
    criteria: tuple[str, ...]
    _index: dict[tuple[str, str, str], int] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._index.update({(g.paper, g.reviewer, g.criterion): g.grade for g in self.grades})

    def paper(self, paper: str) -> PaperEntry:
        for p in self.papers:
            if p.paper == paper:
                return p
        raise KeyError(paper)

    def split(self, name: str) -> tuple[PaperEntry, ...]:
        return tuple(p for p in self.papers if p.split == name)

    def grade(self, paper: str, reviewer: str, criterion: str) -> int:
        return self._index[(paper, reviewer, criterion)]

    def reviewer_total(self, paper: str, reviewer: str) -> int:
        return sum(self.grade(paper, reviewer, c) for c in self.criteria)

    def reviewer_mean(self, paper: str, criterion: str) -> float:
        return sum(self.grade(paper, r, criterion) for r in self.reviewers) / len(self.reviewers)

    def reviewer_means(self, paper: str) -> dict[str, float]:
        return {c: self.reviewer_mean(paper, c) for c in self.criteria}

    def reviewer_mean_total(self, paper: str) -> float:
        return sum(self.reviewer_total(paper, r) for r in self.reviewers) / len(self.reviewers)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_for_prompt(root: Path, prompt_text: str) -> CalibrationSet:
    """Loads a set against the criteria the prompt's own Lua publishes."""
    return load_set(root, prompt_criteria(prompt_text))


def graded_criteria(root: Path) -> tuple[str, ...]:
    """The criteria grades.csv grades, in order of first appearance, unvalidated."""
    text = (Path(root) / "grades.csv").read_bytes().decode("utf-8")
    rows = _read_grades(text, is_synthetic_text(text))
    return tuple(dict.fromkeys(g.criterion for g in rows))


def load_set(root: Path, criteria: Sequence[str]) -> CalibrationSet:
    """Loads and validates the set at `root` against the prompt's criteria.

    To load a set whose criteria may no longer match the prompt, so that the
    mismatch can be reported as a gate, pass `graded_criteria(root)`.
    """
    root = Path(root)
    papers_path, grades_path = root / "papers.jsonl", root / "grades.csv"
    for path in (papers_path, grades_path):
        if not path.is_file():
            raise SetError(f"{path}: missing")
    papers, papers_synthetic = _read_papers(papers_path, root)
    grades_text = grades_path.read_bytes().decode("utf-8")
    flags = {"papers.jsonl": papers_synthetic, "grades.csv": is_synthetic_text(grades_text)}
    readme = root / "README.md"
    if readme.is_file():
        flags["README.md"] = is_synthetic_text(readme.read_bytes().decode("utf-8"))
    if len(set(flags.values())) != 1:
        raise SetError(f"{root}: mixes synthetic and golden files ({_describe(flags)})")
    synthetic = papers_synthetic
    parts = {p.lower() for p in root.resolve().parts}
    if synthetic and "golden" in parts:
        raise SetError(f"{root}: synthetic data under a golden directory")
    if not synthetic and "synthetic" in parts:
        raise SetError(f"{root}: unmarked data under a synthetic directory")

    grades = _read_grades(grades_text, synthetic)
    paper_ids = {p.paper for p in papers}
    for g in grades:
        if g.paper not in paper_ids:
            raise SetError(f"grades.csv: paper {g.paper} is not in papers.jsonl")
    _check_criteria(grades, criteria)
    reviewers = tuple(sorted({g.reviewer for g in grades}))
    seen: set[tuple[str, str, str]] = set()
    for g in grades:
        key = (g.paper, g.reviewer, g.criterion)
        if key in seen:
            raise SetError(f"grades.csv: {', '.join(key)} is graded twice")
        seen.add(key)
    for p in sorted(paper_ids):
        for r in reviewers:
            for c in criteria:
                if (p, r, c) not in seen:
                    raise SetError(f"grades.csv: no grade for {p}, {r}, {c}")
    return CalibrationSet(root=root, synthetic=synthetic, papers=tuple(papers),
                          grades=tuple(grades), reviewers=reviewers, criteria=tuple(criteria))


def _describe(flags: dict[str, bool]) -> str:
    return ", ".join(f"{k} {'synthetic' if v else 'golden'}" for k, v in sorted(flags.items()))


def _read_papers(path: Path, root: Path) -> tuple[list[PaperEntry], bool]:
    entries: list[PaperEntry] = []
    flags: set[bool] = set()
    for n, line in enumerate(path.read_bytes().decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise SetError(f"papers.jsonl line {n}: not JSON ({error})") from error
        if not isinstance(row, dict):
            raise SetError(f"papers.jsonl line {n}: not an object")
        missing = [f for f in PAPER_FIELDS if not isinstance(row.get(f), str) or not row.get(f)]
        if missing:
            raise SetError(f"papers.jsonl line {n}: missing or empty {missing}")
        if row["split"] not in SPLITS:
            raise SetError(f"papers.jsonl line {n}: split {row['split']!r} is none of {SPLITS}")
        flag = row.get("synthetic", False)
        if not isinstance(flag, bool):
            raise SetError(f"papers.jsonl line {n}: synthetic must be true or false")
        flags.add(flag)
        if any(e.paper == row["paper"] for e in entries):
            raise SetError(f"papers.jsonl line {n}: {row['paper']} is listed twice")
        md = root / "papers" / f"{row['paper']}.md"
        if not md.is_file():
            raise SetError(f"papers.jsonl line {n}: {md} is missing")
        digest = sha256_file(md)
        if digest != row["markdown_sha256"]:
            raise SetError(f"papers.jsonl line {n}: {md.name} has sha256 {digest}, "
                           f"pinned {row['markdown_sha256']}")
        entries.append(PaperEntry(paper=row["paper"], markdown_sha256=row["markdown_sha256"],
                                  tomd_version=row["tomd_version"], split=row["split"], path=md))
    if not entries:
        raise SetError("papers.jsonl: no papers")
    if len(flags) != 1:
        raise SetError("papers.jsonl: mixes synthetic and golden lines")
    return entries, flags.pop()


def _read_grades(text: str, synthetic: bool) -> list[Grade]:
    lines = text.splitlines()
    first = 1
    if synthetic:
        lines, first = lines[1:], 2
    reader = csv.reader(io.StringIO("\n".join(lines)))
    header = next(reader, None)
    if header != GRADE_COLUMNS:
        raise SetError(f"grades.csv: header {header}, expected {GRADE_COLUMNS}")
    grades = []
    for n, row in enumerate(reader, start=first + 1):
        if not row:
            continue
        if len(row) != len(GRADE_COLUMNS):
            raise SetError(f"grades.csv line {n}: {len(row)} fields, expected {len(GRADE_COLUMNS)}")
        paper, reviewer, criterion, value = (x.strip() for x in row)
        if not (paper and reviewer and criterion):
            raise SetError(f"grades.csv line {n}: an empty field")
        if value not in GRADE_VALUES:
            raise SetError(f"grades.csv line {n}: grade {value!r} is not 0, 1 or 2")
        grades.append(Grade(paper, reviewer, criterion, int(value)))
    if not grades:
        raise SetError("grades.csv: no grades")
    return grades


def _check_criteria(grades: list[Grade], criteria: Sequence[str]) -> None:
    graded = {g.criterion for g in grades}
    unknown = sorted(graded - set(criteria))
    if unknown:
        raise SetError(f"grades.csv: criteria not in the prompt's CRITERIA table: {unknown}")
    ungraded = sorted(set(criteria) - graded)
    if ungraded:
        raise SetError(f"the prompt's CRITERIA table has criteria with no grades: {ungraded}")
