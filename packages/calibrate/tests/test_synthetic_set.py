# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The checked-in synthetic set: marked, pinned, complete and reproducible."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from calibrate import marking, shim, synthetic


@pytest.fixture(scope="module")
def set_dir(package_root: Path) -> Path:
    return package_root / "data" / "synthetic"


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_every_file_says_it_is_synthetic(set_dir: Path) -> None:
    assert marking.is_synthetic_text((set_dir / "README.md").read_text(encoding="utf-8"))
    assert marking.is_synthetic_text((set_dir / "grades.csv").read_text(encoding="utf-8"))
    for name in ("papers.jsonl", "truth.jsonl"):
        rows = jsonl(set_dir / name)
        assert rows
        assert all(row["synthetic"] is True for row in rows), name


def test_synthetic_files_live_only_where_allowed(package_root: Path) -> None:
    allowed = (package_root / "data" / "synthetic", package_root / "tests" / "fixtures" / "synthetic")
    for path in package_root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".py":
            continue
        head = path.read_bytes()[:200].decode("utf-8", errors="replace")
        marked = marking.is_synthetic_text(head) or '"synthetic": true' in head
        if marked and path.parent.name not in {"examples"}:
            assert any(a in path.parents for a in allowed), path


def test_papers_are_the_tomd_fixtures_pinned_by_hash(set_dir: Path, repo_root: Path) -> None:
    for row in jsonl(set_dir / "papers.jsonl"):
        data = (set_dir / "papers" / f"{row['paper']}.md").read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["markdown_sha256"]
        assert b"\r\n" not in data
        assert synthetic.read_paper(repo_root / row["source"]) == data


def test_ten_proposals_calibrate_and_the_rest_hold_out(set_dir: Path) -> None:
    rows = jsonl(set_dir / "papers.jsonl")
    splits = [r["split"] for r in rows]
    assert splits.count("calibration") == synthetic.CALIBRATION_SIZE
    assert splits.count("holdout") == len(rows) - synthetic.CALIBRATION_SIZE >= 1
    for r in rows:
        text = (set_dir / "papers" / f"{r['paper']}.md").read_text(encoding="utf-8")
        assert shim.triage_reply(r["paper"], text) == shim.PROPOSAL


def test_grades_are_complete_and_in_range(set_dir: Path, prompt_text: str) -> None:
    lines = (set_dir / "grades.csv").read_text(encoding="utf-8").splitlines()[1:]
    rows = list(csv.DictReader(lines))
    papers = {r["paper"] for r in jsonl(set_dir / "papers.jsonl")}
    criteria = set(shim.prompt_criteria(prompt_text))
    keys = {(r["paper"], r["reviewer"], r["criterion"]) for r in rows}
    assert len(keys) == len(rows) == len(papers) * len(synthetic.REVIEWERS) * len(criteria)
    assert {r["grade"] for r in rows} <= {"0", "1", "2"}
    assert {r["criterion"] for r in rows} == criteria


def test_regenerating_gives_the_same_bytes(set_dir: Path, repo_root: Path, prompt_text: str) -> None:
    readme = (set_dir / "README.md").read_text(encoding="utf-8")
    recorded = re.search(r"prompt with sha256\s+`([0-9a-f]{64})`", readme)
    assert recorded, "the README must record the prompt it was generated against"
    if recorded.group(1) != synthetic.prompt_sha256(prompt_text):
        pytest.skip("paperweight.md changed since the synthetic set was generated; "
                    "rerun packages/calibrate/scripts/make_synthetic_set.py")
    files = synthetic.build_set(repo_root, prompt_text)
    on_disk = {p.relative_to(set_dir).as_posix(): p.read_bytes()
               for p in set_dir.rglob("*") if p.is_file()}
    assert on_disk == files
