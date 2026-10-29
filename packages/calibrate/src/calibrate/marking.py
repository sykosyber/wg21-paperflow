# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""How a file says it is synthetic: one rule, shared by every writer and reader.

Markdown, CSV and every report or comment built from synthetic inputs start
with a first line that begins with the word SYNTHETIC. JSON and JSONL carry
`"synthetic": true` instead.
"""

from __future__ import annotations

SYNTHETIC = "SYNTHETIC"

SHIM_BANNER = (
    "SYNTHETIC: produced by the calibration shim from simulated votes; "
    "not a paperweight run, and no finding about paperweight."
)

# A real paperweight run whose agreement is measured against synthetic grades.
GRADES_BANNER = (
    "SYNTHETIC: a real paperweight run, scored against synthetic reviewer grades; "
    "its agreement numbers are no finding about paperweight."
)


def is_synthetic_text(text: str) -> bool:
    """True when the first line starts with the word SYNTHETIC."""
    return text.split("\n", 1)[0].lstrip("﻿").startswith(SYNTHETIC)


def add_banner(text: str, banner: str = SHIM_BANNER) -> str:
    """Puts a SYNTHETIC first line on `text`, once."""
    if not banner.startswith(SYNTHETIC):
        raise ValueError("a synthetic banner must start with the word SYNTHETIC")
    if is_synthetic_text(text):
        return text
    return f"{banner}\n{text}"


def strip_banner(text: str) -> tuple[bool, str]:
    """Splits off a SYNTHETIC first line, if there is one."""
    if is_synthetic_text(text):
        return True, text.split("\n", 1)[1] if "\n" in text else ""
    return False, text
