# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The baseline history: every accepted run, kept on the `calibration` branch.

A history directory (a checkout of the `calibration` branch, never `master`)
holds `history.jsonl`, one line per accepted run, and the run folders under
`runs/`. Synthetic runs are recorded under `synthetic/` instead, with their own
`history.jsonl`, and `baseline` reads only one of the two: a lookup for a real
run never sees a synthetic one, so a synthetic or shim run can never become a
baseline for real runs.

Every accepted run is recorded, replays included, so drift in the model or
the gateway shows up over time. Only full runs are baselines, because replay
needs the recorded votes in a full run's diagnostics.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from calibrate.run import RunFolder

HISTORY = "history.jsonl"
RUNS = "runs"
SYNTHETIC_DIR = "synthetic"


class HistoryError(RuntimeError):
    """A history that cannot be written or read as asked."""


def root_for(base: Path, synthetic: bool) -> Path:
    return base / SYNTHETIC_DIR if synthetic else base


def entries(base: Path, synthetic: bool) -> list[dict]:
    path = root_for(base, synthetic) / HISTORY
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_bytes().decode("utf-8").splitlines() if line.strip()]
    for row in rows:
        if bool(row.get("synthetic")) != synthetic:
            raise HistoryError(f"{path}: a {'real' if synthetic else 'synthetic'} entry in the "
                               f"{'synthetic' if synthetic else 'real'} history")
    return rows


def record(base: Path, folder: RunFolder, *, note: str = "",
           now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> dict:
    """Copies an accepted run into the history and appends its line."""
    root = root_for(base, folder.synthetic)
    dest = root / RUNS / folder.path.name
    if dest.exists():
        raise HistoryError(f"{dest} is already recorded")
    shutil.copytree(folder.path, dest, ignore=shutil.ignore_patterns("prompt.patched", "stderr.txt"))
    meta = folder.meta
    entry = {
        "synthetic": folder.synthetic, "run": f"{RUNS}/{folder.path.name}", "mode": meta.get("mode"),
        "model": meta.get("model"), "prompt_sha256": meta.get("prompt_sha256"),
        "backend": meta.get("backend"), "repeats": meta.get("repeats"),
        "partial": meta.get("partial", False), "recorded_at": now().isoformat(timespec="seconds"),
        "note": note,
    }
    with (root / HISTORY).open("ab") as f:
        f.write((json.dumps(entry, sort_keys=True) + "\n").encode("utf-8"))
    return entry


def baseline(base: Path, model: str, *, synthetic: bool) -> Path | None:
    """The last full, complete run recorded for `model`, from one history only."""
    root = root_for(base, synthetic)
    for row in reversed(entries(base, synthetic)):
        if row.get("model") == model and row.get("mode") == "full" and not row.get("partial"):
            path = root / row["run"]
            if not (path / "meta.json").is_file():
                raise HistoryError(f"{path}: recorded but missing")
            return path
    return None
