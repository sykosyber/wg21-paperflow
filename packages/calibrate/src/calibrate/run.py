# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Full runs: every paper in a set, `repeats` times, through one backend.

Two backends.

- `shim` runs the prompt's own Lua with the simulated grader and no model
  (`calibrate.shim`). It is the default when no gateway is configured, and
  everything it writes is marked SYNTHETIC.
- `binary` runs the real `paperweight` executable, found through
  `PAPERWEIGHT_BIN` or `PATH`, with the gateway it reads from
  `RUNVIL_GATEWAY_URL` and `RUNVIL_GATEWAY_API_KEY`. paperweight keeps the
  diagnostics in its store, so the harness passes a copy of the prompt whose
  Analyze epilogue appends them to `report.md` (`diagnostics_patch`), and
  records that it did.

A run folder holds `meta.json`, the prompt as given (`prompt.md`), and one
`<paper>.r<n>/` per paper and repeat with `report.md`, `diagnostics.md` and
`result.json`. Papers run in parallel up to `jobs`; the repeats of one paper
run one after another. A run that exits non-zero, writes a report the parser
cannot read, or reports missing replies is kept and counted, never retried.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from calibrate import __version__, aggregate, diagnostics, marking, shim, simulate, synthetic
from calibrate.golden import CalibrationSet, PaperEntry

log = logging.getLogger(__name__)

RUNS_DIR = Path("calibration-runs")
DEFAULT_REPEATS = 3
DEFAULT_JOBS = 4
DEFAULT_SEED = 1
# A paperweight run over one paper takes minutes, not hours.
BINARY_TIMEOUT_SECONDS = 3600
VERSION_TIMEOUT_SECONDS = 30
STDERR_TAIL_LINES = 40

GATEWAY_URL = "RUNVIL_GATEWAY_URL"
GATEWAY_KEY = "RUNVIL_GATEWAY_API_KEY"
BINARY_ENV = "PAPERWEIGHT_BIN"
BINARY_NAME = "paperweight"

OK, INCOMPLETE, FAILED = "ok", "incomplete", "failed"

# The commented appendix in the Analyze epilogue, and the report write, as
# paperweight.md has them. `diagnostics_patch` restores the one and adds it
# to the other; if either text moves, the patch refuses to apply.
COMMENTED_APPENDIX = (
    '--   local diag = read_or_empty("diagnostics.md")\n'
    '--   local appendix = diag:find("%S")\n'
    '--       and ("\\n\\n<!-- paperweight-diagnostics\\n" .. diag .. "\\n-->\\n") or ""'
)
RESTORED_APPENDIX = (
    'local diag = read_or_empty("diagnostics.md")\n'
    'local appendix = diag:find("%S")\n'
    '    and ("\\n\\n<!-- paperweight-diagnostics\\n" .. diag .. "\\n-->\\n") or ""'
)
REPORT_WRITE = 'store.write("report.md", weight_line .. "\\n\\n" .. body .. "\\n")'
PATCHED_WRITE = 'store.write("report.md", weight_line .. "\\n\\n" .. body .. "\\n" .. appendix)'


class RunnerError(RuntimeError):
    """A run cannot start: no binary, no gateway, a prompt the patch does not fit."""


def gateway_configured(env: dict[str, str] | None = None) -> bool:
    env = dict(os.environ) if env is None else env
    return bool(env.get(GATEWAY_URL, "").strip() and env.get(GATEWAY_KEY, "").strip())


def diagnostics_patch(prompt_text: str) -> str:
    """A copy of the prompt whose Analyze epilogue appends diagnostics.md to the report.

    Only the Analyze epilogue changes: the commented appendix is restored and
    added to the `store.write("report.md", ...)` line. Raises `RunnerError`
    when either text is not found exactly once there.
    """
    text = prompt_text.replace("\r\n", "\n")
    block = shim.parse_prompt(text).analyze_epilogue
    code = block.code
    for needle in (COMMENTED_APPENDIX, REPORT_WRITE):
        if code.count(needle) != 1:
            raise RunnerError(
                "the diagnostics patch no longer fits paperweight.md's Analyze epilogue: "
                f"{needle.splitlines()[0]!r} occurs {code.count(needle)} times")
    patched = code.replace(COMMENTED_APPENDIX, RESTORED_APPENDIX).replace(REPORT_WRITE, PATCHED_WRITE)
    lines = text.split("\n")
    start = sum(len(line) + 1 for line in lines[:block.first_line - 1])
    return text[:start] + patched + text[start + len(code):]


# --- results ---------------------------------------------------------------------


@dataclass
class Outcome:
    """What one backend run produced, before the harness judges it."""

    exit_code: int
    report: str | None
    diagnostics: str | None
    error: str = ""
    wall_seconds: float = 0.0
    stderr: str = ""


def judge(outcome: Outcome, paper: str, repeat: int, synthetic: bool) -> dict:
    """The result record for one run: status, the verdict, the numbers compare reads."""
    result: dict = {
        "paper": paper, "repeat": repeat, "synthetic": synthetic, "status": FAILED,
        "exit_code": outcome.exit_code, "error": outcome.error,
        "wall_seconds": round(outcome.wall_seconds, 3),
    }
    if outcome.exit_code != 0:
        result["error"] = outcome.error or f"exited {outcome.exit_code}"
        return result
    if outcome.report is None or outcome.diagnostics is None:
        result["error"] = outcome.error or "no report or no diagnostics"
        return result
    try:
        report = diagnostics.split_report(outcome.report)
        d = diagnostics.parse_diagnostics(outcome.diagnostics)
    except diagnostics.DiagnosticsError as error:
        result["error"] = f"unparseable: {error}"
        return result
    if report.synthetic != synthetic or d.synthetic != synthetic:
        result["error"] = "SYNTHETIC marking does not match the backend"
        return result
    result.update({
        "weight_line": report.weight.line, "span": report.weight.span,
        "shown": report.weight.shown, "is_proposal": d.is_proposal,
        "model_calls": d.model_calls,
    })
    if not d.is_proposal:
        result.update({"status": OK, "total": None, "grades": {}, "missing": 0, "rejected": 0})
        return result
    result.update({
        "total": float(d.points), "total_text": d.points, "inter_rule": d.inter_rule,
        "totals_by_rule": d.totals, "grades": {k: float(v) for k, v in (d.grades or {}).items()},
        "sample_totals": list(d.single_sample_totals), "unanimous": d.unanimous,
        "pairs": d.pairs, "rejected": d.rejected, "missing": d.missing,
        "sections": d.sections, "samples": d.samples,
    })
    result["status"] = INCOMPLETE if d.missing else OK
    if d.missing:
        result["error"] = f"{d.missing} replies missing"
    return result


# --- backends ----------------------------------------------------------------------


@dataclass
class ShimBackend:
    """The Lua shim with the simulated grader. Always synthetic."""

    prompt_text: str
    profile: simulate.GraderProfile
    seed: int = DEFAULT_SEED
    truth_seed: int = synthetic.TRUTH_SEED
    perf: Callable[[], float] = time.perf_counter
    name: str = "shim"
    synthetic: bool = True

    def model_id(self, requested: str | None) -> str:
        return f"shim-{self.profile.name}"

    def describe(self) -> dict:
        return {"lua": shim.DEFAULT_LUA, "profile": self.profile.name, "seed": self.seed,
                "truth_seed": self.truth_seed, "diagnostics_from": "store"}

    def prepare(self, run_dir: Path) -> None:
        return None

    def run(self, paper: PaperEntry, repeat: int, workdir: Path) -> Outcome:
        grader = simulate.SimulatedGrader(self.profile, truth_seed=self.truth_seed,
                                          noise_seed=self.seed * 1000 + repeat)
        start = self.perf()
        try:
            done = shim.run_paper(self.prompt_text, paper.text(), grader, paper_id=paper.paper)
        except shim.ShimError as error:
            return Outcome(exit_code=1, report=None, diagnostics=None, error=str(error),
                           wall_seconds=self.perf() - start)
        return Outcome(exit_code=0, report=marking.add_banner(done.report),
                       diagnostics=marking.add_banner(done.diagnostics),
                       wall_seconds=self.perf() - start)


def find_binary(env: dict[str, str] | None = None) -> Path:
    env = dict(os.environ) if env is None else env
    explicit = env.get(BINARY_ENV, "").strip()
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise RunnerError(f"{BINARY_ENV}={explicit} is not a file")
        return path
    found = shutil.which(BINARY_NAME, path=env.get("PATH"))
    if not found:
        raise RunnerError(f"no {BINARY_NAME} binary: set {BINARY_ENV} or put it on PATH")
    return Path(found)


@dataclass
class BinaryBackend:
    """The real paperweight binary, given a prompt copy that appends diagnostics.

    `prepare` writes that copy into the run folder as
    `prompt.patched/paperweight.md`, so the run keeps paperweight's name
    (paperweight names a run after the prompt's file stem).
    """

    binary: Path
    prompt_text: str = field(repr=False)
    model: str | None
    # Holds the gateway key: never in a repr, a log line or run metadata.
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ), repr=False)
    timeout: float = BINARY_TIMEOUT_SECONDS
    perf: Callable[[], float] = time.perf_counter
    name: str = "binary"
    synthetic: bool = False
    patched_prompt: Path | None = None

    def model_id(self, requested: str | None) -> str:
        return requested or "gateway-default"

    def prepare(self, run_dir: Path) -> None:
        folder = run_dir / "prompt.patched"
        folder.mkdir()
        self.patched_prompt = folder / "paperweight.md"
        self.patched_prompt.write_bytes(diagnostics_patch(self.prompt_text).encode("utf-8"))

    def version(self) -> str:
        try:
            done = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True,
                                  timeout=VERSION_TIMEOUT_SECONDS, env=self.env, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            return f"unknown ({error})"
        return done.stdout.strip() or f"unknown (exit {done.returncode})"

    def describe(self) -> dict:
        return {"binary": str(self.binary), "binary_version": self.version(),
                "diagnostics_from": "report appendix, via a patched prompt copy (prompt.patched/paperweight.md)"}

    def run(self, paper: PaperEntry, repeat: int, workdir: Path) -> Outcome:
        if self.patched_prompt is None:
            raise RunnerError("BinaryBackend.prepare must run before run")
        out = workdir / "report.md"
        cmd = [str(self.binary), "--file", str(paper.path), "--output", str(out),
               "--prompt", str(self.patched_prompt)]
        if self.model:
            cmd += ["--model", self.model]
        start = self.perf()
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=self.timeout, env=self.env, check=False)
        except subprocess.TimeoutExpired:
            return Outcome(exit_code=-1, report=None, diagnostics=None,
                           error=f"timed out after {self.timeout:.0f}s", wall_seconds=self.perf() - start)
        except OSError as error:
            return Outcome(exit_code=-1, report=None, diagnostics=None, error=str(error),
                           wall_seconds=self.perf() - start)
        wall = self.perf() - start
        stderr = "\n".join(done.stderr.splitlines()[-STDERR_TAIL_LINES:])
        if done.returncode != 0:
            return Outcome(exit_code=done.returncode, report=None, diagnostics=None,
                           error=stderr.splitlines()[-1] if stderr else "", wall_seconds=wall,
                           stderr=done.stderr)
        if not out.is_file():
            return Outcome(exit_code=0, report=None, diagnostics=None,
                           error="exited 0 without writing the report", wall_seconds=wall, stderr=done.stderr)
        report = out.read_bytes().decode("utf-8", errors="replace")
        try:
            diag = diagnostics.split_report(report).diagnostics_text
        except diagnostics.DiagnosticsError as error:
            return Outcome(exit_code=0, report=report, diagnostics=None,
                           error=f"unparseable: {error}", wall_seconds=wall, stderr=done.stderr)
        if diag is None:
            return Outcome(exit_code=0, report=report, diagnostics=None,
                           error="the report has no diagnostics appendix", wall_seconds=wall,
                           stderr=done.stderr)
        return Outcome(exit_code=0, report=report, diagnostics=diag, wall_seconds=wall, stderr=done.stderr)


# --- the run ---------------------------------------------------------------------


@dataclass(frozen=True)
class RunConfig:
    prompt_path: Path
    model: str | None = None
    repeats: int = DEFAULT_REPEATS
    jobs: int = DEFAULT_JOBS
    papers: Sequence[str] = ()
    runs_dir: Path = RUNS_DIR
    out: Path | None = None


def portable(path: Path) -> str:
    """A path relative to the working directory when it lies under it, so a run
    folder still points at its set on another machine or in CI."""
    try:
        return Path(path).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "model"


def select_papers(cset: CalibrationSet, wanted: Sequence[str]) -> list[PaperEntry]:
    if not wanted:
        return list(cset.papers)
    known = {p.paper for p in cset.papers}
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise RunnerError(f"papers not in the set: {', '.join(unknown)}")
    return [p for p in cset.papers if p.paper in set(wanted)]


def run_dir_for(config: RunConfig, prompt_text: str, model_id: str, now: datetime) -> Path:
    if config.out is not None:
        return config.out
    sha8 = synthetic.prompt_sha256(prompt_text)[:8]
    base = config.runs_dir / f"{now:%Y-%m-%d}-{sha8}-{safe_name(model_id)}"
    path, n = base, 1
    while path.exists():
        n += 1
        path = base.with_name(f"{base.name}-{n}")
    return path


def write_json(path: Path, data: dict) -> None:
    path.write_bytes((json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def full_run(config: RunConfig, backend: ShimBackend | BinaryBackend, cset: CalibrationSet, *,
             now: Callable[[], datetime] = lambda: datetime.now(UTC),
             perf: Callable[[], float] = time.perf_counter) -> Path:
    """Runs every selected paper `repeats` times and writes the run folder."""
    if config.repeats < 1 or config.jobs < 1:
        raise RunnerError("repeats and jobs must be at least 1")
    prompt_text =config.prompt_path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    constants = aggregate.EpilogueConstants.from_prompt(prompt_text)
    papers = select_papers(cset, config.papers)
    model_id = backend.model_id(config.model)
    started = now()
    run_dir = run_dir_for(config, prompt_text, model_id, started)
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "prompt.md").write_bytes(prompt_text.encode("utf-8"))
    backend.prepare(run_dir)
    # Synthetic grades or a synthetic backend make the whole run synthetic.
    synthetic_run = backend.synthetic or cset.synthetic
    # The shim's banner says no model ran; a real run on synthetic grades says only the grades are.
    banner = marking.SHIM_BANNER if backend.synthetic else marking.GRADES_BANNER
    meta = {
        "synthetic": synthetic_run, "mode": "full", "backend": backend.name,
        "harness_version": __version__, "model": model_id,
        "prompt_path": portable(config.prompt_path), "prompt_sha256": synthetic.prompt_sha256(prompt_text),
        "constants": constants.to_dict(), "repeats": config.repeats, "jobs": config.jobs,
        "papers": [p.paper for p in papers], "partial": bool(config.papers),
        "splits": {p.paper: p.split for p in papers},
        "set": {"root": portable(cset.root), "synthetic": cset.synthetic},
        "started_at": started.isoformat(timespec="seconds"), "status": "running",
        **backend.describe(),
    }
    write_json(run_dir / "meta.json", meta)

    def one_paper(paper: PaperEntry) -> list[dict]:
        results = []
        for repeat in range(1, config.repeats + 1):
            workdir = run_dir / f"{paper.paper}.r{repeat}"
            workdir.mkdir()
            outcome = backend.run(paper, repeat, workdir)
            if outcome.report is not None:
                (workdir / "report.md").write_bytes(_mark(outcome.report, synthetic_run, banner).encode("utf-8"))
            if outcome.diagnostics is not None:
                (workdir / "diagnostics.md").write_bytes(
                    _mark(outcome.diagnostics, synthetic_run, banner).encode("utf-8"))
            if outcome.stderr:
                (workdir / "stderr.txt").write_bytes(outcome.stderr.encode("utf-8"))
            result = judge(Outcome(outcome.exit_code, _maybe_mark(outcome.report, synthetic_run, banner),
                                   _maybe_mark(outcome.diagnostics, synthetic_run, banner), outcome.error,
                                   outcome.wall_seconds), paper.paper, repeat, synthetic_run)
            write_json(workdir / "result.json", result)
            if result["status"] != OK:
                log.warning("%s r%d: %s (%s)", paper.paper, repeat, result["status"], result["error"])
            results.append(result)
        return results

    t0 = perf()
    with ThreadPoolExecutor(max_workers=config.jobs) as pool:
        per_paper = list(pool.map(one_paper, papers))
    results = [r for rs in per_paper for r in rs]
    meta.update({
        "status": "done", "finished_at": now().isoformat(timespec="seconds"),
        "wall_seconds": round(perf() - t0, 3),
        "runs": len(results), "runs_failed": sum(r["status"] == FAILED for r in results),
        "runs_incomplete": sum(r["status"] == INCOMPLETE for r in results),
        "model_calls": sum(r.get("model_calls") or 0 for r in results),
    })
    write_json(run_dir / "meta.json", meta)
    return run_dir


def _mark(text: str, synthetic_run: bool, banner: str) -> str:
    return marking.add_banner(text, banner) if synthetic_run else text


def _maybe_mark(text: str | None, synthetic_run: bool, banner: str) -> str | None:
    return None if text is None else _mark(text, synthetic_run, banner)


def make_binary_backend(prompt_text: str, model: str | None,
                        env: dict[str, str] | None = None) -> BinaryBackend:
    """Checks the gateway, the binary and the patch before any run starts."""
    env = dict(os.environ) if env is None else env
    if not gateway_configured(env):
        raise RunnerError(f"{GATEWAY_URL} and {GATEWAY_KEY} must both be set for the binary backend")
    diagnostics_patch(prompt_text)
    return BinaryBackend(binary=find_binary(env), prompt_text=prompt_text, model=model, env=env)


# --- reading a run back -----------------------------------------------------------------


@dataclass(frozen=True)
class RunFolder:
    """A run folder read back: its metadata, prompt and per-run results."""

    path: Path
    meta: dict
    prompt_text: str
    results: tuple[dict, ...]

    @property
    def synthetic(self) -> bool:
        return bool(self.meta.get("synthetic"))

    @property
    def constants(self) -> aggregate.EpilogueConstants:
        return aggregate.EpilogueConstants.from_dict(self.meta["constants"])

    def by_paper(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for r in sorted(self.results, key=lambda r: (r["paper"], r["repeat"])):
            out.setdefault(r["paper"], []).append(r)
        return out

    def run_path(self, paper: str, repeat: int) -> Path:
        return self.path / f"{paper}.r{repeat}"


def load_run(path: Path) -> RunFolder:
    meta_path = path / "meta.json"
    if not meta_path.is_file():
        raise RunnerError(f"{path} is not a run folder: no meta.json")
    meta = json.loads(meta_path.read_bytes().decode("utf-8"))
    if "synthetic" not in meta:
        raise RunnerError(f"{meta_path} does not say whether the run is synthetic")
    results = []
    for result_path in sorted(path.glob("*.r*/result.json")):
        r = json.loads(result_path.read_bytes().decode("utf-8"))
        if bool(r.get("synthetic")) != bool(meta["synthetic"]):
            raise RunnerError(f"{result_path}: synthetic marking differs from the run's")
        results.append(r)
    prompt = (path / "prompt.md").read_bytes().decode("utf-8")
    return RunFolder(path=path, meta=meta, prompt_text=prompt, results=tuple(results))
