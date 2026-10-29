# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Regenerate packages/calibrate/data/synthetic/ from the current prompt.

SYNTHETIC: the set this writes is simulated reviewers on real papers.

    uv run python packages/calibrate/scripts/make_synthetic_set.py [--out DIR]
"""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

from calibrate import synthetic

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT = REPO_ROOT / "crates" / "paperweight" / "paperweight.md"
DEFAULT_OUT = REPO_ROOT / "packages" / "calibrate" / "data" / "synthetic"

log = logging.getLogger("make_synthetic_set")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if "golden" in {p.lower() for p in args.out.resolve().parts}:
        parser.error("refusing to write synthetic data under a golden directory")
    prompt = PROMPT.read_bytes().decode("utf-8")
    files = synthetic.build_set(REPO_ROOT, prompt)
    if (args.out / "papers").is_dir():
        shutil.rmtree(args.out / "papers")
    for rel, data in sorted(files.items()):
        path = args.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    log.info("wrote %d files to %s", len(files), args.out)


if __name__ == "__main__":
    main()
