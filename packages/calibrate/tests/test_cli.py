# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The command line, end to end on the synthetic set with the shim."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from calibrate import aggregate, run
from calibrate.__main__ import main, pick_backend

SET = "packages/calibrate/data/synthetic"


@pytest.fixture(autouse=True)
def at_repo_root(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    monkeypatch.chdir(repo_root)
    monkeypatch.delenv(run.GATEWAY_URL, raising=False)
    monkeypatch.delenv(run.GATEWAY_KEY, raising=False)


def test_the_backend_follows_the_gateway() -> None:
    assert pick_backend(None, {}) == "shim"
    assert pick_backend(None, {run.GATEWAY_URL: "http://gw", run.GATEWAY_KEY: "k"}) == "binary"
    assert pick_backend("shim", {run.GATEWAY_URL: "http://gw", run.GATEWAY_KEY: "k"}) == "shim"
    assert pick_backend(None, {run.GATEWAY_URL: "http://gw"}) == "shim"


def test_full_replay_compare_report(tmp_path: Path, prompt_text: str, capsys) -> None:
    base = tmp_path / "base"
    assert main(["full", "--set", SET, "--papers", "P0533R9,P1068R11,P3953R0", "--repeats", "2",
                 "--jobs", "2", "--out", str(base)]) == 0
    assert capsys.readouterr().out.strip() == str(base)
    meta = json.loads((base / "meta.json").read_text(encoding="utf-8"))
    assert meta["synthetic"] is True and meta["backend"] == "shim" and meta["model"] == "shim-calibrated"

    candidate = tmp_path / "candidate.md"
    candidate.write_bytes(aggregate.patch_constants(prompt_text, INTER_RULE="max").encode("utf-8"))
    assert main(["choose", "--prompt", str(candidate), "--from", str(base)]) == 0
    assert capsys.readouterr().out.startswith("replay\n")

    replayed = tmp_path / "max"
    assert main(["replay", "--prompt", str(candidate), "--from", str(base), "--out", str(replayed)]) == 0
    capsys.readouterr()

    comment = tmp_path / "comment.md"
    assert main(["compare", str(replayed), str(base), "--out", str(comment)]) == 0
    printed = capsys.readouterr().out
    assert printed == comment.read_text(encoding="utf-8")
    assert printed.startswith("SYNTHETIC")
    assert "Gates: 4 of 4 pass" in printed

    assert main(["report", str(base)]) == 0
    capsys.readouterr()
    assert (base / "summary.md").read_text(encoding="utf-8").startswith("SYNTHETIC")
    assert json.loads((base / "summary.json").read_text(encoding="utf-8"))["synthetic"] is True


def test_compare_exits_1_when_a_gate_fails(tmp_path: Path, capsys) -> None:
    base = tmp_path / "base"
    assert main(["full", "--set", SET, "--papers", "P3953R0", "--repeats", "1", "--out", str(base)]) == 0
    result = base / "P3953R0.r1" / "result.json"
    data = json.loads(result.read_text(encoding="utf-8"))
    data.update(status="failed", error="exited 1")
    result.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert main(["compare", str(base)]) == 1
    assert "Gate 1 fails" in capsys.readouterr().out


def test_choose_says_full_for_a_criterion_change(tmp_path: Path, prompt_text: str, capsys) -> None:
    base = tmp_path / "base"
    main(["full", "--set", SET, "--papers", "P3953R0", "--repeats", "1", "--out", str(base)])
    candidate = tmp_path / "candidate.md"
    candidate.write_text(prompt_text.replace("does not count.", "does not count at all.", 1), encoding="utf-8")
    capsys.readouterr()
    main(["choose", "--prompt", str(candidate), "--from", str(base)])
    assert capsys.readouterr().out.startswith("full\n")


def test_replay_refusal_is_a_clean_error(tmp_path: Path, prompt_text: str) -> None:
    base = tmp_path / "base"
    main(["full", "--set", SET, "--papers", "P3953R0", "--repeats", "1", "--out", str(base)])
    candidate = tmp_path / "candidate.md"
    candidate.write_text(prompt_text.replace("local QUOTE_WORDS = 40", "local QUOTE_WORDS = 30"), encoding="utf-8")
    with pytest.raises(SystemExit, match="a full run is needed"):
        main(["replay", "--prompt", str(candidate), "--from", str(base), "--out", str(tmp_path / "r")])


def test_the_golden_set_is_never_swapped_silently(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="the golden set has not arrived yet"):
        main(["full", "--out", str(tmp_path / "x")])
    assert not (tmp_path / "x").exists()


def test_binary_without_a_gateway_is_a_clean_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="must both be set"):
        main(["full", "--backend", "binary", "--set", SET, "--out", str(tmp_path / "x")])


def test_check_set(capsys) -> None:
    assert main(["check-set", "--set", SET]) == 0
    assert "SYNTHETIC set, 12 papers (10 calibration, 2 holdout)" in capsys.readouterr().out
