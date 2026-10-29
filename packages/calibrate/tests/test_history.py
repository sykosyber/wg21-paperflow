# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The baseline history, and the CI workflow that keeps it."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from calibrate import aggregate, golden, history, replay, run, simulate
from calibrate.__main__ import main

FIXED = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def clock() -> datetime:
    return FIXED


@pytest.fixture(scope="module")
def base_run(tmp_path_factory, prompt_text: str, package_root: Path) -> run.RunFolder:
    tmp = tmp_path_factory.mktemp("hist")
    cset = golden.load_for_prompt(package_root / "data" / "synthetic", prompt_text)
    prompt = tmp / "p.md"
    prompt.write_bytes(prompt_text.encode("utf-8"))
    backend = run.ShimBackend(prompt_text=prompt_text, profile=simulate.PROFILES["calibrated"])
    config = run.RunConfig(prompt_path=prompt, repeats=1, jobs=2, out=tmp / "2026-10-26-base")
    return run.load_run(run.full_run(config, backend, cset, now=clock))


def make_real(tmp_path: Path, folder: run.RunFolder) -> run.RunFolder:
    """A copy marked real, to stand in for a run on golden data."""
    real = tmp_path / "2026-10-26-real"
    shutil.copytree(folder.path, real)
    for path in [real / "meta.json", *real.glob("*.r*/result.json")]:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["synthetic"] = False
        if path.name == "meta.json":
            data["model"] = "qwen3"
        path.write_text(json.dumps(data), encoding="utf-8")
    return run.load_run(real)


def test_a_synthetic_run_is_recorded_apart(tmp_path: Path, base_run) -> None:
    entry = history.record(tmp_path, base_run, now=clock)
    assert entry["synthetic"] is True and entry["mode"] == "full"
    assert (tmp_path / "synthetic" / "history.jsonl").is_file()
    assert (tmp_path / "synthetic" / "runs" / base_run.path.name / "meta.json").is_file()
    assert not (tmp_path / "history.jsonl").exists()
    assert history.baseline(tmp_path, "shim-calibrated", synthetic=True) == (
        tmp_path / "synthetic" / "runs" / base_run.path.name)
    # A real lookup never sees it.
    assert history.baseline(tmp_path, "shim-calibrated", synthetic=False) is None


def test_a_real_run_is_recorded_in_the_real_history(tmp_path: Path, base_run) -> None:
    real = make_real(tmp_path / "work", base_run)
    history.record(tmp_path / "hist", real, now=clock)
    assert history.baseline(tmp_path / "hist", "qwen3", synthetic=False) == tmp_path / "hist" / "runs" / real.path.name
    assert history.baseline(tmp_path / "hist", "qwen3", synthetic=True) is None


def test_a_planted_synthetic_line_in_the_real_history_is_refused(tmp_path: Path, base_run) -> None:
    (tmp_path / "history.jsonl").write_text(json.dumps({"synthetic": True, "model": "x"}) + "\n",
                                            encoding="utf-8")
    with pytest.raises(history.HistoryError, match="synthetic entry in the real history"):
        history.baseline(tmp_path, "x", synthetic=False)


def test_only_full_complete_runs_are_baselines(tmp_path: Path, base_run, prompt_text: str) -> None:
    history.record(tmp_path, base_run, now=clock)
    replayed = replay.replay_run(base_run, aggregate.patch_constants(prompt_text, INTER_RULE="max"),
                                 tmp_path / "work" / "2026-10-26-max", now=clock)
    history.record(tmp_path, run.load_run(replayed), now=clock)
    assert len(history.entries(tmp_path, synthetic=True)) == 2
    assert history.baseline(tmp_path, "shim-calibrated", synthetic=True).name == base_run.path.name
    with pytest.raises(history.HistoryError, match="already recorded"):
        history.record(tmp_path, base_run, now=clock)


def test_record_and_baseline_on_the_command_line(tmp_path: Path, base_run, capsys) -> None:
    assert main(["record", str(base_run.path), "--history", str(tmp_path)]) == 0
    assert "SYNTHETIC history" in capsys.readouterr().out
    assert main(["baseline", "--history", str(tmp_path), "--model", "shim-calibrated", "--synthetic"]) == 0
    assert capsys.readouterr().out.strip().endswith(base_run.path.name)
    assert main(["baseline", "--history", str(tmp_path), "--model", "shim-calibrated"]) == 1


# --- the workflow -----------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow(repo_root: Path) -> str:
    return (repo_root / ".github" / "workflows" / "calibrate.yml").read_text(encoding="utf-8")


def test_the_workflow_never_pushes_to_master(workflow: str) -> None:
    pushes = re.findall(r"git push[^\n]*", workflow)
    assert pushes and all("calibration" in p for p in pushes), pushes
    assert "master" not in " ".join(pushes)


def test_the_full_run_skips_cleanly_without_the_gateway(workflow: str) -> None:
    assert "secrets.RUNVIL_GATEWAY_URL" in workflow
    assert "RUNVIL_GATEWAY_URL is not set" in workflow


def test_the_workflow_uses_the_tests_artifact_and_marks_synthetic(workflow: str) -> None:
    assert "paperweight-linux-x86_64" in workflow
    assert "--synthetic" in workflow
    assert "crates/paperweight/paperweight.md" in workflow
