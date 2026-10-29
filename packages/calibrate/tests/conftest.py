# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Shared fixtures. Tests take these as parameters; nothing imports this module."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_PATH = REPO_ROOT / "crates" / "paperweight" / "paperweight.md"
IDEALS = REPO_ROOT / "packages" / "tomd" / "tests" / "fixtures" / "golden" / "ideals"
PACKAGE_ROOT = REPO_ROOT / "packages" / "calibrate"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def package_root() -> Path:
    return PACKAGE_ROOT


@pytest.fixture(scope="session")
def prompt_text() -> str:
    """The current paperweight.md, with line endings as git stores them."""
    return PROMPT_PATH.read_bytes().decode("utf-8").replace("\r\n", "\n")


@pytest.fixture(scope="session")
def ideal_paper():
    """Reads a tomd golden paper by file stem, as stored (LF line endings)."""
    def read(stem: str) -> str:
        return (IDEALS / f"{stem}.md").read_bytes().decode("utf-8").replace("\r\n", "\n")
    return read
