# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The runner: the diagnostics patch, the shim and binary backends, run
folders, concurrency, and failure accounting. No gateway, no network."""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from calibrate import diagnostics, golden, marking, run, shim, simulate

FAKE = Path(__file__).parent / "fixtures" / "fake_paperweight.py"
FIXED = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def clock() -> datetime:
    return FIXED


def ticks():
    n = iter(range(10**6))
    return lambda: float(next(n))


@pytest.fixture(scope="module")
def synthetic_set(package_root: Path, prompt_text: str) -> golden.CalibrationSet:
    return golden.load_for_prompt(package_root / "data" / "synthetic", prompt_text)


@pytest.fixture
def prompt_file(tmp_path: Path, prompt_text: str) -> Path:
    path = tmp_path / "candidate" / "paperweight.md"
    path.parent.mkdir()
    path.write_bytes(prompt_text.encode("utf-8"))
    return path


# --- the diagnostics patch -----------------------------------------------------------


def test_the_patch_applies_cleanly_to_the_current_prompt(prompt_text: str) -> None:
    patched = run.diagnostics_patch(prompt_text)
    before, after = shim.parse_prompt(prompt_text), shim.parse_prompt(patched)
    for name in ("setup", "assess_prologue", "assess_epilogue", "grade_prologue",
                 "grade_epilogue", "analyze_prologue"):
        assert getattr(before, name).code == getattr(after, name).code, name
    assert before.analyze_epilogue.code != after.analyze_epilogue.code
    assert run.RESTORED_APPENDIX in after.analyze_epilogue.code
    assert run.PATCHED_WRITE in after.analyze_epilogue.code
    assert run.COMMENTED_APPENDIX not in after.analyze_epilogue.code
    assert run.diagnostics_patch(prompt_text.replace("\n", "\r\n")) == patched


def test_the_patched_prompt_appends_the_diagnostics(prompt_text: str, ideal_paper) -> None:
    grader = simulate.SimulatedGrader(simulate.PROFILES["noisy"], truth_seed=1, noise_seed=2)
    plain = shim.run_paper(prompt_text, ideal_paper("p4228r0"), grader, paper_id="P4228R0")
    grader = simulate.SimulatedGrader(simulate.PROFILES["noisy"], truth_seed=1, noise_seed=2)
    patched = shim.run_paper(run.diagnostics_patch(prompt_text), ideal_paper("p4228r0"), grader,
                             paper_id="P4228R0")
    report = diagnostics.split_report(patched.report)
    assert report.diagnostics_text == patched.diagnostics == plain.diagnostics
    # Everything before the appendix is the unpatched report, byte for byte.
    assert patched.report.startswith(plain.report)


@pytest.mark.parametrize("anchor", [run.COMMENTED_APPENDIX.split("\n")[0], run.REPORT_WRITE])
def test_the_patch_refuses_a_prompt_it_does_not_fit(prompt_text: str, anchor: str) -> None:
    moved = prompt_text.replace(anchor, anchor.replace("report.md", "report2.md").replace("diag", "dg"))
    with pytest.raises(run.RunnerError, match="no longer fits"):
        run.diagnostics_patch(moved)


# --- the shim backend --------------------------------------------------------------------


def shim_run(tmp_path: Path, prompt_file: Path, cset: golden.CalibrationSet, name: str,
             papers=("P0533R9", "P3953R0", "P4228R0"), repeats: int = 2, seed: int = 7) -> Path:
    backend = run.ShimBackend(prompt_text=prompt_file.read_text(encoding="utf-8"),
                              profile=simulate.PROFILES["noisy"], seed=seed, perf=ticks())
    config = run.RunConfig(prompt_path=prompt_file, repeats=repeats, jobs=2, papers=papers,
                           out=tmp_path / name)
    return run.full_run(config, backend, cset, now=clock, perf=ticks())


def test_a_shim_run_writes_a_marked_run_folder(tmp_path: Path, prompt_file: Path, synthetic_set) -> None:
    folder = shim_run(tmp_path, prompt_file, synthetic_set, "a")
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["synthetic"] is True and meta["backend"] == "shim" and meta["status"] == "done"
    assert meta["model"] == "shim-noisy" and meta["partial"] is True
    assert meta["runs"] == 6 and meta["runs_failed"] == 0
    assert meta["constants"]["INTER_RULE"] == "top2"
    assert (folder / "prompt.md").read_text(encoding="utf-8") == prompt_file.read_text(encoding="utf-8")
    for paper in ("P0533R9", "P3953R0", "P4228R0"):
        for r in (1, 2):
            d = folder / f"{paper}.r{r}"
            report = (d / "report.md").read_text(encoding="utf-8")
            assert marking.is_synthetic_text(report)
            assert report.split("\n")[1].startswith("Weight: ")
            assert marking.is_synthetic_text((d / "diagnostics.md").read_text(encoding="utf-8"))
            result = json.loads((d / "result.json").read_text(encoding="utf-8"))
            assert result["status"] == "ok" and result["synthetic"] is True
            assert result["model_calls"] > 2


def test_shim_runs_are_reproducible(tmp_path: Path, prompt_file: Path, synthetic_set) -> None:
    a = run.load_run(shim_run(tmp_path, prompt_file, synthetic_set, "a"))
    b = run.load_run(shim_run(tmp_path, prompt_file, synthetic_set, "b"))
    c = run.load_run(shim_run(tmp_path, prompt_file, synthetic_set, "c", seed=8))

    def strip(r: run.RunFolder) -> list[dict]:
        return [{k: v for k, v in x.items() if k != "wall_seconds"} for x in r.results]
    assert strip(a) == strip(b)
    assert strip(a) != strip(c)
    # Repeats of one paper differ: the noise seed follows the repeat.
    p = a.by_paper()["P0533R9"]
    assert p[0]["sample_totals"] != p[1]["sample_totals"]


def test_the_run_folder_name(tmp_path: Path, prompt_file: Path, synthetic_set) -> None:
    backend = run.ShimBackend(prompt_text=prompt_file.read_text(encoding="utf-8"),
                              profile=simulate.PROFILES["calibrated"])
    config = run.RunConfig(prompt_path=prompt_file, repeats=1, jobs=1, papers=("P3953R0",),
                           runs_dir=tmp_path / "runs")
    first = run.full_run(config, backend, synthetic_set, now=clock)
    second = run.full_run(config, backend, synthetic_set, now=clock)
    sha8 = json.loads((first / "meta.json").read_text(encoding="utf-8"))["prompt_sha256"][:8]
    assert first.name == f"2026-10-26-{sha8}-shim-calibrated"
    assert second.name == first.name + "-2"


def test_unknown_papers_are_refused(tmp_path: Path, prompt_file: Path, synthetic_set) -> None:
    with pytest.raises(run.RunnerError, match="P9999R0"):
        shim_run(tmp_path, prompt_file, synthetic_set, "x", papers=("P9999R0",))


# --- concurrency -------------------------------------------------------------------------


class RecordingBackend:
    """In-process backend that records events and returns a fixed good run."""

    name = "recording"
    synthetic = True

    def __init__(self, report: str, diag: str, barrier_papers: set[str]) -> None:
        self.report, self.diag = report, diag
        self.events: list[tuple[str, str, int]] = []
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(len(barrier_papers), timeout=30)
        self.barrier_papers = barrier_papers

    def model_id(self, requested: str | None) -> str:
        return "recording"

    def describe(self) -> dict:
        return {}

    def prepare(self, run_dir: Path) -> None:
        return None

    def run(self, paper, repeat: int, workdir: Path) -> run.Outcome:
        with self.lock:
            self.events.append(("start", paper.paper, repeat))
        if repeat == 1 and paper.paper in self.barrier_papers:
            # Every paper in the barrier must be in flight at once, or this times out.
            self.barrier.wait()
        with self.lock:
            self.events.append(("end", paper.paper, repeat))
        return run.Outcome(exit_code=0, report=self.report, diagnostics=self.diag)


def test_papers_run_in_parallel_and_repeats_in_order(tmp_path: Path, prompt_file: Path,
                                                     synthetic_set) -> None:
    grader = simulate.SimulatedGrader(simulate.PROFILES["calibrated"], truth_seed=1, noise_seed=1)
    text = synthetic_set.paper("P3953R0").text()
    done = shim.run_paper(prompt_file.read_text(encoding="utf-8"), text, grader, paper_id="P3953R0")
    papers = ("P0533R9", "P1068R11", "P3953R0")
    backend = RecordingBackend(marking.add_banner(done.report), marking.add_banner(done.diagnostics),
                               set(papers))
    config = run.RunConfig(prompt_path=prompt_file, repeats=3, jobs=3, papers=papers,
                           out=tmp_path / "parallel")
    folder = run.full_run(config, backend, synthetic_set, now=clock)  # type: ignore[arg-type]
    assert json.loads((folder / "meta.json").read_text(encoding="utf-8"))["runs"] == 9
    for paper in papers:
        mine = [(kind, r) for kind, p, r in backend.events if p == paper]
        assert mine == [("start", 1), ("end", 1), ("start", 2), ("end", 2), ("start", 3), ("end", 3)]


# --- the binary backend, against a fake paperweight ---------------------------------------


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if os.name == "nt":
        (bindir / "paperweight.cmd").write_text(f'@echo off\r\n"{sys.executable}" "{FAKE}" %*\r\n',
                                                 encoding="utf-8")
    else:
        script = bindir / "paperweight"
        script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
        script.chmod(0o755)
    return bindir


# Only what a Python child process needs to start. The real environment is never
# copied, so no credential on the machine can reach a test or its failure output.
CHILD_ENV_KEYS = ("SYSTEMROOT", "SystemRoot", "PATHEXT", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE")


@pytest.fixture
def fake_env(tmp_path: Path, fake_bin: Path) -> dict[str, str]:
    env = {k: os.environ[k] for k in CHILD_ENV_KEYS if k in os.environ}
    env["PATH"] = str(fake_bin) + os.pathsep + os.path.dirname(sys.executable)
    env[run.GATEWAY_URL] = "http://gateway.invalid"
    env[run.GATEWAY_KEY] = "not-a-real-key"
    log = tmp_path / "invocations"
    log.mkdir()
    env["FAKE_PAPERWEIGHT_LOG"] = str(log)
    return env


def binary_run(tmp_path: Path, prompt_file: Path, cset, env: dict[str, str], plan: dict[str, str],
               papers: tuple[str, ...], repeats: int = 2, name: str = "binary-run") -> Path:
    env = dict(env, FAKE_PAPERWEIGHT_PLAN=json.dumps(plan))
    backend = run.make_binary_backend(prompt_file.read_text(encoding="utf-8"), "test-model", env)
    config = run.RunConfig(prompt_path=prompt_file, model="test-model", repeats=repeats, jobs=2,
                           papers=papers, out=tmp_path / name)
    return run.full_run(config, backend, cset, now=clock)


def invocations(env: dict[str, str]) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(env["FAKE_PAPERWEIGHT_LOG"]).glob("*.json"))]


def test_the_binary_backend_reads_diagnostics_from_the_report(tmp_path: Path, prompt_file: Path,
                                                             synthetic_set, fake_env, prompt_text: str) -> None:
    folder = binary_run(tmp_path, prompt_file, synthetic_set, fake_env, {}, ("P3953R0", "P4228R0"))
    loaded = run.load_run(folder)
    assert [r["status"] for r in loaded.results] == ["ok"] * 4
    # On the synthetic set the run is synthetic even though the backend is real.
    assert loaded.synthetic and loaded.meta["backend"] == "binary"
    assert loaded.meta["binary_version"] == "paperweight 0.0.0-fake"
    calls = invocations(fake_env)
    assert len(calls) == 4 and {c["model"] for c in calls} == {"test-model"}
    patched = Path(calls[0]["prompt"])
    assert patched.name == "paperweight.md" and patched.parent == folder / "prompt.patched"
    assert patched.read_text(encoding="utf-8") == run.diagnostics_patch(prompt_text)
    d = folder / "P3953R0.r1"
    report_text = (d / "report.md").read_text(encoding="utf-8")
    assert marking.is_synthetic_text(report_text)
    # A real run on synthetic grades says so, and does not claim to be the shim.
    assert report_text.splitlines()[0] == marking.GRADES_BANNER
    assert diagnostics.parse_diagnostics((d / "diagnostics.md").read_text(encoding="utf-8")).is_proposal


def test_failures_are_kept_counted_and_never_retried(tmp_path: Path, prompt_file: Path,
                                                     synthetic_set, fake_env) -> None:
    plan = {"P0533R9": "exit1", "P0957R8": "missing", "P1068R11": "garbage", "P1122R3": "noappendix"}
    folder = binary_run(tmp_path, prompt_file, synthetic_set, fake_env, plan,
                        ("P0533R9", "P0957R8", "P1068R11", "P1122R3", "P3953R0"))
    status = {(r["paper"], r["repeat"]): r for r in run.load_run(folder).results}
    assert {status[("P0533R9", n)]["status"] for n in (1, 2)} == {"failed"}
    assert status[("P0533R9", 1)]["exit_code"] == 1
    assert "gateway refused" in status[("P0533R9", 1)]["error"]
    assert (folder / "P0533R9.r1" / "stderr.txt").is_file()
    assert {status[("P0957R8", n)]["status"] for n in (1, 2)} == {"incomplete"}
    assert status[("P0957R8", 1)]["missing"] > 0
    assert "unparseable" in status[("P1068R11", 1)]["error"]
    assert status[("P1122R3", 1)]["error"] == "the report has no diagnostics appendix"
    assert {status[("P3953R0", n)]["status"] for n in (1, 2)} == {"ok"}
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert (meta["runs"], meta["runs_failed"], meta["runs_incomplete"]) == (10, 6, 2)
    counts: dict[str, int] = {}
    for call in invocations(fake_env):
        counts[call["paper"]] = counts.get(call["paper"], 0) + 1
    assert set(counts.values()) == {2}, counts


def test_the_binary_backend_needs_a_gateway(prompt_text: str, fake_env) -> None:
    env = dict(fake_env)
    env.pop(run.GATEWAY_KEY)
    with pytest.raises(run.RunnerError, match="must both be set"):
        run.make_binary_backend(prompt_text, None, env)
    assert not run.gateway_configured(env)


def test_the_binary_comes_from_the_environment_first(tmp_path: Path, fake_env) -> None:
    explicit = tmp_path / "pw-explicit"
    explicit.write_text("", encoding="utf-8")
    assert run.find_binary(dict(fake_env, PAPERWEIGHT_BIN=str(explicit))) == explicit
    with pytest.raises(run.RunnerError, match="is not a file"):
        run.find_binary(dict(fake_env, PAPERWEIGHT_BIN=str(tmp_path / "missing")))
    assert run.find_binary(fake_env).stem == "paperweight"
    with pytest.raises(run.RunnerError, match="no paperweight binary"):
        run.find_binary({"PATH": str(tmp_path / "empty")})


def test_load_run_refuses_mixed_marking(tmp_path: Path, prompt_file: Path, synthetic_set) -> None:
    folder = shim_run(tmp_path, prompt_file, synthetic_set, "m", papers=("P3953R0",), repeats=1)
    result = folder / "P3953R0.r1" / "result.json"
    data = json.loads(result.read_text(encoding="utf-8"))
    data["synthetic"] = False
    result.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(run.RunnerError, match="synthetic marking differs"):
        run.load_run(folder)
