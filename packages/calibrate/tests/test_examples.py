# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The checked-in acceptance example stays marked and stays what it says it is."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from calibrate import aggregate, replay, synthetic


@pytest.fixture(scope="module")
def examples(package_root: Path) -> Path:
    return package_root / "examples"


def test_the_comment_is_marked_synthetic(examples: Path) -> None:
    text = (examples / "synthetic-comment.md").read_text(encoding="utf-8")
    first, second = text.split("\n")[:2]
    assert first.startswith("SYNTHETIC")
    assert second.startswith("### Paperweight calibration · replay · 10 papers × 3 repeats")
    assert "Gates: 4 of 4 pass" in text
    assert (examples / "README.md").read_text(encoding="utf-8").startswith("SYNTHETIC")


def test_the_bias_moved_up(examples: Path) -> None:
    text = (examples / "synthetic-comment.md").read_text(encoding="utf-8")
    row = re.search(r"^\| Bias \| (\S+) \| (\S+) \| (\S+) \(", text, re.M)
    assert row is not None
    assert float(row.group(2)) > float(row.group(1)) and float(row.group(3)) > 0


def test_the_candidate_changes_only_inter_rule(examples: Path, prompt_text: str) -> None:
    readme = (examples / "README.md").read_text(encoding="utf-8")
    recorded = re.search(r"sha256 `([0-9a-f]{8})`", readme)
    assert recorded
    if recorded.group(1) != synthetic.prompt_sha256(prompt_text)[:8]:
        pytest.skip("paperweight.md changed since the examples were made; see examples/README.md")
    candidate = replay.load_prompt(examples / "candidate-inter-rule-max.md")
    assert candidate == aggregate.patch_constants(prompt_text, INTER_RULE="max")
    assert replay.choose_mode(prompt_text, candidate).mode == replay.REPLAY
