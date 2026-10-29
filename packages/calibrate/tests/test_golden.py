# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The set loader: the synthetic set loads, broken copies fail loudly, and
synthetic and golden data never mix."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from calibrate import golden, marking, shim


@pytest.fixture(scope="module")
def synthetic_dir(package_root: Path) -> Path:
    return package_root / "data" / "synthetic"


@pytest.fixture
def copy(tmp_path: Path, synthetic_dir: Path):
    """Copies the synthetic set into tmp_path/<name> and returns the copy."""
    def make(name: str = "set") -> Path:
        dst = tmp_path / name
        shutil.copytree(synthetic_dir, dst)
        return dst
    return make


def rewrite(path: Path, old: str, new: str, count: int = -1) -> None:
    text = path.read_bytes().decode("utf-8")
    assert old in text
    path.write_bytes(text.replace(old, new, count).encode("utf-8"))


def unmark(root: Path) -> None:
    """Turns a copy of the synthetic set into an unmarked (golden-shaped) one."""
    for name in ("grades.csv", "README.md"):
        _, text = marking.strip_banner((root / name).read_bytes().decode("utf-8"))
        (root / name).write_bytes(text.encode("utf-8"))
    rows = [json.loads(x) for x in (root / "papers.jsonl").read_text(encoding="utf-8").splitlines()]
    for r in rows:
        del r["synthetic"]
    (root / "papers.jsonl").write_bytes("".join(json.dumps(r) + "\n" for r in rows).encode("utf-8"))


def test_the_synthetic_set_loads(synthetic_dir: Path, prompt_text: str) -> None:
    s = golden.load_for_prompt(synthetic_dir, prompt_text)
    assert s.synthetic
    assert len(s.split("calibration")) == 10 and len(s.split("holdout")) == 2
    assert s.criteria == shim.prompt_criteria(prompt_text)
    assert s.reviewers == ("SYN-A", "SYN-B", "SYN-C")
    assert len(s.grades) == 12 * 3 * 7
    p = s.papers[0].paper
    assert s.reviewer_mean_total(p) == pytest.approx(
        sum(s.reviewer_total(p, r) for r in s.reviewers) / 3)
    assert sum(s.reviewer_means(p).values()) == pytest.approx(s.reviewer_mean_total(p))


def test_the_golden_directory_is_empty_until_the_data_arrives(package_root: Path, prompt_text: str) -> None:
    root = package_root / "data" / "golden"
    assert sorted(p.name for p in root.iterdir()) == [".gitkeep", "README.md"]
    with pytest.raises(golden.SetError, match="missing"):
        golden.load_for_prompt(root, prompt_text)


def test_a_renamed_criterion_fails(copy, prompt_text: str) -> None:
    root = copy()
    rewrite(root / "grades.csv", ",prior_art,", ",prior_art_and_alternatives,")
    with pytest.raises(golden.SetError, match=r"not in the prompt's CRITERIA table: \['prior_art_and_alternatives'\]"):
        golden.load_for_prompt(root, prompt_text)


def test_a_criterion_the_prompt_lacks_in_grades_fails(synthetic_dir: Path) -> None:
    criteria = ("motivation", "audience", "prior_art", "vehicle", "coordination",
                "insufficiency", "implementation", "novelty")
    with pytest.raises(golden.SetError, match=r"no grades: \['novelty'\]"):
        golden.load_set(synthetic_dir, criteria)


def test_a_wrong_hash_fails(copy, prompt_text: str) -> None:
    root = copy()
    md = root / "papers" / "P0533R9.md"
    md.write_bytes(md.read_bytes() + b"\n")
    with pytest.raises(golden.SetError, match="P0533R9.md has sha256"):
        golden.load_for_prompt(root, prompt_text)


def test_crlf_changes_the_hash(copy, prompt_text: str) -> None:
    root = copy()
    md = root / "papers" / "P3953R0.md"
    md.write_bytes(md.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(golden.SetError, match="P3953R0.md has sha256"):
        golden.load_for_prompt(root, prompt_text)


def test_a_grade_of_3_fails(copy, prompt_text: str) -> None:
    root = copy()
    rewrite(root / "grades.csv", "P0533R9,SYN-A,motivation,1", "P0533R9,SYN-A,motivation,3")
    with pytest.raises(golden.SetError, match="grade '3' is not 0, 1 or 2"):
        golden.load_for_prompt(root, prompt_text)


@pytest.mark.parametrize(("old", "new", "message"), [
    ("P0533R9,SYN-A,motivation,1\n", "", "no grade for P0533R9, SYN-A, motivation"),
    ("P0533R9,SYN-A,motivation,1\n", "P0533R9,SYN-A,motivation,1\nP0533R9,SYN-A,motivation,1\n",
     "graded twice"),
    ("paper,reviewer,criterion,grade", "paper,reviewer,criterion,score", "header"),
    ("P0533R9,SYN-A,motivation,1\n", "P9999R0,SYN-A,motivation,1\n", "P9999R0 is not in papers.jsonl"),
])
def test_grade_rows_are_validated(copy, prompt_text: str, old: str, new: str, message: str) -> None:
    root = copy()
    rewrite(root / "grades.csv", old, new, 1)
    with pytest.raises(golden.SetError, match=message):
        golden.load_for_prompt(root, prompt_text)


@pytest.mark.parametrize(("field", "value", "message"), [
    ("split", "training", "split 'training'"),
    ("tomd_version", "", "missing or empty"),
    ("paper", "P0000R0", "P0000R0.md is missing"),
])
def test_paper_lines_are_validated(copy, prompt_text: str, field: str, value: str, message: str) -> None:
    root = copy()
    lines = (root / "papers.jsonl").read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row[field] = value
    lines[0] = json.dumps(row)
    (root / "papers.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    with pytest.raises(golden.SetError, match=message):
        golden.load_for_prompt(root, prompt_text)


# --- synthetic and golden never mix ------------------------------------------------


def test_a_marked_csv_with_unmarked_papers_is_refused(copy, prompt_text: str) -> None:
    root = copy()
    unmark(root)
    grades = (root / "grades.csv").read_bytes().decode("utf-8")
    (root / "grades.csv").write_bytes(("SYNTHETIC: stray\n" + grades).encode("utf-8"))
    with pytest.raises(golden.SetError, match="mixes synthetic and golden files"):
        golden.load_for_prompt(root, prompt_text)


def test_one_unmarked_jsonl_line_is_refused(copy, prompt_text: str) -> None:
    root = copy()
    lines = (root / "papers.jsonl").read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[3])
    del row["synthetic"]
    lines[3] = json.dumps(row)
    (root / "papers.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    with pytest.raises(golden.SetError, match="mixes synthetic and golden lines"):
        golden.load_for_prompt(root, prompt_text)


def test_synthetic_data_under_golden_is_refused(copy, prompt_text: str) -> None:
    root = copy("golden")
    with pytest.raises(golden.SetError, match="synthetic data under a golden directory"):
        golden.load_for_prompt(root, prompt_text)


def test_unmarked_data_under_synthetic_is_refused(copy, prompt_text: str) -> None:
    root = copy("synthetic")
    unmark(root)
    with pytest.raises(golden.SetError, match="unmarked data under a synthetic directory"):
        golden.load_for_prompt(root, prompt_text)


def test_an_unmarked_set_loads_as_golden(copy, prompt_text: str) -> None:
    root = copy("golden")
    unmark(root)
    s = golden.load_for_prompt(root, prompt_text)
    assert not s.synthetic
    assert len(s.grades) == 12 * 3 * 7
