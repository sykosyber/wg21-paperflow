# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""Record replay-parity fixtures by running the shim on paperweight.md.

SYNTHETIC: every fixture is the real Lua's output on simulated votes.

    uv run python packages/calibrate/scripts/make_parity_fixtures.py

Writes packages/calibrate/tests/fixtures/synthetic/parity/: for each case a
`<name>.report.md` and a `<name>.diagnostics.md`, both exactly as the Lua
wrote them under a SYNTHETIC first line, and `index.jsonl`, which records the
paper, its hash, the grader settings and every epilogue constant in force.
Edge-case papers derived from real ones go to `../papers/`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import re
import shutil
from pathlib import Path

from calibrate import aggregate, marking, shim, simulate, synthetic

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT = REPO_ROOT / "crates" / "paperweight" / "paperweight.md"
SET_DIR = REPO_ROOT / "packages" / "calibrate" / "data" / "synthetic"
OUT = REPO_ROOT / "packages" / "calibrate" / "tests" / "fixtures" / "synthetic"
IDEALS = REPO_ROOT / synthetic.IDEALS_DIR

TRUTH_SEED = synthetic.TRUTH_SEED
PROFILE_CYCLE = ("calibrated", "prior_art_overgrade", "insufficiency_undergrade", "noisy")

log = logging.getLogger("make_parity_fixtures")


@dataclasses.dataclass(frozen=True)
class Case:
    paper: str
    paper_path: Path
    profile: str
    noise_seed: int
    variant: dict
    edge: str | None = None
    invalid_quote_rate: float = 0.0
    missing_rate: float = 0.0


def derived_papers() -> dict[str, tuple[str, str]]:
    """Edge-case papers made from real ones: name -> (paper id, text)."""
    p3978 = synthetic.read_paper(IDEALS / "p3978r0.md").decode("utf-8")
    p3953 = synthetic.read_paper(IDEALS / "p3953r0.md").decode("utf-8")
    demoted = re.sub(r"(?m)^## ", "### ", p3978)
    flattened = re.sub(r"(?m)^#{1,6}\s+", "", p3953)
    return {
        "P3978R0-h3-fallback": ("P3978R0", marking.add_banner(
            demoted, "SYNTHETIC test input: P3978R0 with every H2 demoted to H3, "
                     "so the prologue falls back from H2 headings.")),
        "P3953R0-single-section": ("P3953R0", marking.add_banner(
            flattened, "SYNTHETIC test input: P3953R0 with every heading marker removed, "
                       "so the prologue finds a single section.")),
    }


def cases(papers_dir: Path) -> list[Case]:
    rows = [json.loads(line) for line in (SET_DIR / "papers.jsonl").read_text(encoding="utf-8").splitlines()]
    cal = [r["paper"] for r in rows if r["split"] == "calibration"]
    hold = [r["paper"] for r in rows if r["split"] == "holdout"]

    def path(pid: str) -> Path:
        return SET_DIR / "papers" / f"{pid}.md"

    out = []
    for i, rule in enumerate(aggregate.RULES):
        for j, pid in enumerate(cal):
            out.append(Case(pid, path(pid), PROFILE_CYCLE[(i + j) % len(PROFILE_CYCLE)],
                            1000 + 10 * i + j, {"INTER_RULE": rule}))
    out.append(Case(hold[0], path(hold[0]), "noisy", 2001, {}, invalid_quote_rate=0.2))
    out.append(Case(hold[1], path(hold[1]), "calibrated", 2002, {}, missing_rate=0.05))
    out += [
        Case("P1068R11", path("P1068R11"), "noisy", 3001,
             {"LABELS": [(0, "Weightless"), (2, "Light"), (6, "Medium"), (10, "Heavy"), (14, "Supermassive")]}),
        Case("P3556R0", path("P3556R0"), "noisy", 3002,
             {"INTER_RULE": "corroborated", "STRONG": 1.0, "CORROBORATION": 3}),
        Case("P0957R8", path("P0957R8"), "noisy", 3003, {"EDGE_WINDOW": 1.5}),
        Case("P3290R4", path("P3290R4"), "noisy", 3004, {"INTER_RULE": "accumulate", "ACCUM_FULL": 3.0}),
        Case("P3411R5", path("P3411R5"), "noisy", 3005, {"BINARY": []}),
    ]
    derived = derived_papers()
    out += [
        Case("P3978R0", papers_dir / "P3978R0-h3-fallback.md", "noisy", 4001, {}, edge="h2 fallback"),
        Case("N5040", IDEALS / "n5040.md", "noisy", 4002, {}, edge="not a proposal"),
        Case("P0533R9", path("P0533R9"), "all_zero", 4003, {}, edge="all-zero votes"),
        Case("P3953R0", papers_dir / "P3953R0-single-section.md", "noisy", 4004, {}, edge="single section"),
    ]
    for name, (_, text) in derived.items():
        (papers_dir / f"{name}.md").write_bytes(text.encode("utf-8"))
    return out


def variant_name(variant: dict) -> str:
    if not variant:
        return "default"
    return "-".join(f"{k.lower()}_{v if not isinstance(v, list) else len(v)}" for k, v in variant.items())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    base = PROMPT.read_bytes().decode("utf-8").replace("\r\n", "\n")
    parity = OUT / "parity"
    papers_dir = OUT / "papers"
    for d in (parity, papers_dir):
        if d.is_dir():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    index = []
    for n, case in enumerate(cases(papers_dir), start=1):
        prompt = aggregate.patch_constants(base, **case.variant) if case.variant else base
        constants = aggregate.EpilogueConstants.from_prompt(prompt)
        profile = dataclasses.replace(simulate.PROFILES[case.profile],
                                      invalid_quote_rate=case.invalid_quote_rate,
                                      missing_rate=case.missing_rate)
        grader = simulate.SimulatedGrader(profile, truth_seed=TRUTH_SEED, noise_seed=case.noise_seed)
        paper_bytes = synthetic.read_paper(case.paper_path)
        run = shim.run_paper(prompt, paper_bytes.decode("utf-8"), grader, paper_id=case.paper)
        name = f"{n:02d}-{case.paper}-{variant_name(case.variant)}-{case.profile}"
        (parity / f"{name}.report.md").write_bytes(marking.add_banner(run.report).encode("utf-8"))
        (parity / f"{name}.diagnostics.md").write_bytes(marking.add_banner(run.diagnostics).encode("utf-8"))
        index.append({
            "synthetic": True, "name": name, "paper": case.paper,
            "paper_file": case.paper_path.relative_to(REPO_ROOT).as_posix(),
            "paper_sha256": hashlib.sha256(paper_bytes).hexdigest(),
            "profile": case.profile, "truth_seed": TRUTH_SEED, "noise_seed": case.noise_seed,
            "invalid_quote_rate": case.invalid_quote_rate, "missing_rate": case.missing_rate,
            "variant": {k: v for k, v in case.variant.items()}, "constants": constants.to_dict(),
            "edge": case.edge, "lua": shim.DEFAULT_LUA, "model_calls": run.model_calls,
            "prompt_sha256": synthetic.prompt_sha256(prompt),
        })
    (parity / "index.jsonl").write_bytes(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in index).encode("utf-8"))
    log.info("wrote %d parity fixtures to %s", len(index), parity)


if __name__ == "__main__":
    main()
