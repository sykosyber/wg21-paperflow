# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""`uv run calibrate <verb>`: full, replay, compare, report, and the helpers CI uses.

    full     --prompt P [--model ID] [--backend shim|binary] [--set DIR] [--papers A,B]
             [--repeats 3] [--jobs 4] [--seed 1] [--profile calibrated] [--out DIR]
    replay   --prompt P --from RUN [--out DIR]
    compare  CANDIDATE [BASELINE] [--set DIR] [--out FILE]
    report   RUN [--set DIR]
    choose   --prompt P --from RUN          prints replay or full, and why
    record   RUN --history DIR [--note N]   appends an accepted run to the history
    baseline --history DIR --model ID [--synthetic]
    check-set [--set DIR] [--prompt P]

The backend defaults to `binary` when RUNVIL_GATEWAY_URL and
RUNVIL_GATEWAY_API_KEY are set, and to `shim` otherwise; a shim run is
always SYNTHETIC. The set defaults to data/golden/ and is never swapped for
the synthetic one silently. `compare` exits 1 when a gate fails.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from calibrate import compare, golden, history, replay, run, score, simulate, synthetic
from calibrate.marking import SYNTHETIC

log = logging.getLogger("calibrate")

PROMPT = Path("crates") / "paperweight" / "paperweight.md"
GOLDEN = Path("packages") / "calibrate" / "data" / "golden"
SYNTHETIC_SET = Path("packages") / "calibrate" / "data" / "synthetic"

EXIT_OK, EXIT_FAIL = 0, 1


def repo_root(start: Path | None = None) -> Path:
    """The nearest directory, from `start` upward, that holds paperweight.md."""
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / PROMPT).is_file():
            return d
    return here


def out(text: str) -> None:
    """Writes UTF-8 to stdout whatever the console's code page."""
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.flush()


def load_set(path: Path, prompt_text: str) -> golden.CalibrationSet:
    try:
        return golden.load_for_prompt(path, prompt_text)
    except golden.SetError as error:
        hint = ""
        if not (path / "papers.jsonl").is_file() and path.name == "golden":
            hint = (f"; the golden set has not arrived yet: pass --set {SYNTHETIC_SET.as_posix()} "
                    "for a SYNTHETIC run")
        raise SystemExit(f"calibrate: {error}{hint}") from error


def pick_backend(name: str | None, env: dict[str, str]) -> str:
    if name:
        return name
    return "binary" if run.gateway_configured(env) else "shim"


def cmd_full(args: argparse.Namespace) -> int:
    root = repo_root()
    prompt_path = args.prompt or root / PROMPT
    prompt_text = replay.load_prompt(prompt_path)
    cset = load_set(args.set or root / GOLDEN, prompt_text)
    backend_name = pick_backend(args.backend, dict(os.environ))
    if backend_name == "shim":
        if args.profile not in simulate.PROFILES:
            raise SystemExit(f"calibrate: unknown profile {args.profile}; one of {sorted(simulate.PROFILES)}")
        log.warning("%s: the shim backend calls no model; this run is synthetic", SYNTHETIC)
        backend: run.ShimBackend | run.BinaryBackend = run.ShimBackend(
            prompt_text=prompt_text, profile=simulate.PROFILES[args.profile], seed=args.seed)
    else:
        backend = run.make_binary_backend(prompt_text, args.model)
    papers = tuple(p.strip() for p in args.papers.split(",") if p.strip()) if args.papers else ()
    config = run.RunConfig(prompt_path=prompt_path, model=args.model, repeats=args.repeats, jobs=args.jobs,
                           papers=papers, runs_dir=args.runs_dir, out=args.out)
    folder = run.full_run(config, backend, cset)
    meta = run.load_run(folder).meta
    out(f"{folder}\n")
    log.info("%d runs, %d failed, %d incomplete", meta["runs"], meta["runs_failed"], meta["runs_incomplete"])
    return EXIT_OK


def cmd_replay(args: argparse.Namespace) -> int:
    source = run.load_run(args.from_run)
    candidate = replay.load_prompt(args.prompt)
    target = args.out or args.runs_dir / (
        f"{datetime.now(UTC):%Y-%m-%d}-{synthetic.prompt_sha256(candidate)[:8]}-"
        f"{run.safe_name(source.meta.get('model', 'model'))}-replay")
    try:
        folder = replay.replay_run(source, candidate, target)
    except replay.ReplayError as error:
        raise SystemExit(f"calibrate: {error}") from error
    out(f"{folder}\n")
    return EXIT_OK


def set_for(folder: run.RunFolder, override: Path | None) -> golden.CalibrationSet:
    root = override or Path(folder.meta["set"]["root"])
    criteria = golden.graded_criteria(root)
    return golden.load_set(root, criteria)


def cmd_compare(args: argparse.Namespace) -> int:
    cand = run.load_run(args.candidate)
    base = run.load_run(args.baseline) if args.baseline else None
    try:
        cmp = compare.compare(cand, base, set_for(cand, args.set))
    except compare.CompareError as error:
        raise SystemExit(f"calibrate: {error}") from error
    text = compare.render_comment(cmp)
    if args.out:
        args.out.write_bytes(text.encode("utf-8"))
    out(text)
    return EXIT_OK if cmp.passed else EXIT_FAIL


def cmd_report(args: argparse.Namespace) -> int:
    folder = run.load_run(args.run)
    scores = score.score_run(folder, set_for(folder, args.set))
    score.write_summary(scores)
    out(f"{folder.path / 'summary.md'}\n")
    return EXIT_OK


def cmd_choose(args: argparse.Namespace) -> int:
    source = run.load_run(args.from_run)
    choice = replay.choose_mode(source.prompt_text, replay.load_prompt(args.prompt))
    out(f"{choice.mode}\n{choice.reason}\n")
    return EXIT_OK


def cmd_record(args: argparse.Namespace) -> int:
    folder = run.load_run(args.run)
    try:
        entry = history.record(args.history, folder, note=args.note)
    except history.HistoryError as error:
        raise SystemExit(f"calibrate: {error}") from error
    where = "the SYNTHETIC history" if folder.synthetic else "the history"
    out(f"recorded {entry['run']} in {where} at {args.history}\n")
    return EXIT_OK


def cmd_baseline(args: argparse.Namespace) -> int:
    found = history.baseline(args.history, args.model, synthetic=args.synthetic)
    if found is None:
        log.info("no %sbaseline for model %s", "SYNTHETIC " if args.synthetic else "", args.model)
        return EXIT_FAIL
    out(f"{found}\n")
    return EXIT_OK


def cmd_check_set(args: argparse.Namespace) -> int:
    root = repo_root()
    prompt_text = replay.load_prompt(args.prompt or root / PROMPT)
    cset = load_set(args.set or root / GOLDEN, prompt_text)
    kind = "SYNTHETIC" if cset.synthetic else "golden"
    out(f"{cset.root}: {kind} set, {len(cset.papers)} papers "
        f"({len(cset.split('calibration'))} calibration, {len(cset.split('holdout'))} holdout), "
        f"{len(cset.reviewers)} reviewers, {len(cset.grades)} grades, criteria match the prompt\n")
    return EXIT_OK


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="calibrate", description="Calibration harness for paperweight.")
    sub = p.add_subparsers(dest="verb", required=True)

    full = sub.add_parser("full", help="run the set through a backend and write a run folder")
    full.add_argument("--prompt", type=Path)
    full.add_argument("--model")
    full.add_argument("--backend", choices=("shim", "binary"))
    full.add_argument("--set", type=Path)
    full.add_argument("--papers", help="comma-separated subset; the comment says it is partial")
    full.add_argument("--repeats", type=int, default=run.DEFAULT_REPEATS)
    full.add_argument("--jobs", type=int, default=run.DEFAULT_JOBS)
    full.add_argument("--seed", type=int, default=run.DEFAULT_SEED, help="shim noise seed")
    full.add_argument("--profile", default="calibrated", help="shim grader profile")
    full.add_argument("--runs-dir", type=Path, default=run.RUNS_DIR)
    full.add_argument("--out", type=Path)
    full.set_defaults(func=cmd_full)

    rp = sub.add_parser("replay", help="re-aggregate a full run under a candidate prompt, no model calls")
    rp.add_argument("--prompt", type=Path, required=True)
    rp.add_argument("--from", dest="from_run", type=Path, required=True)
    rp.add_argument("--runs-dir", type=Path, default=run.RUNS_DIR)
    rp.add_argument("--out", type=Path)
    rp.set_defaults(func=cmd_replay)

    cp = sub.add_parser("compare", help="gates, readings and the comment")
    cp.add_argument("candidate", type=Path)
    cp.add_argument("baseline", type=Path, nargs="?")
    cp.add_argument("--set", type=Path)
    cp.add_argument("--out", type=Path)
    cp.set_defaults(func=cmd_compare)

    rep = sub.add_parser("report", help="write summary.md and summary.json for one run")
    rep.add_argument("run", type=Path)
    rep.add_argument("--set", type=Path)
    rep.set_defaults(func=cmd_report)

    ch = sub.add_parser("choose", help="say whether a candidate can be replayed against a run")
    ch.add_argument("--prompt", type=Path, required=True)
    ch.add_argument("--from", dest="from_run", type=Path, required=True)
    ch.set_defaults(func=cmd_choose)

    rec = sub.add_parser("record", help="append an accepted run to a baseline history")
    rec.add_argument("run", type=Path)
    rec.add_argument("--history", type=Path, required=True, help="a checkout of the calibration branch")
    rec.add_argument("--note", default="")
    rec.set_defaults(func=cmd_record)

    bl = sub.add_parser("baseline", help="print the baseline run for a model, or exit 1")
    bl.add_argument("--history", type=Path, required=True)
    bl.add_argument("--model", required=True)
    bl.add_argument("--synthetic", action="store_true", help="look in the SYNTHETIC history")
    bl.set_defaults(func=cmd_baseline)

    cs = sub.add_parser("check-set", help="validate a calibration set against the prompt")
    cs.add_argument("--set", type=Path)
    cs.add_argument("--prompt", type=Path)
    cs.set_defaults(func=cmd_check_set)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="calibrate: %(message)s")
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (run.RunnerError, golden.SetError) as error:
        raise SystemExit(f"calibrate: {error}") from error


if __name__ == "__main__":
    sys.exit(main())
