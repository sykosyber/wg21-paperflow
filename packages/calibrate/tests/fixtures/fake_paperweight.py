# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""A stand-in for the paperweight binary, for the binary backend's tests.

It takes paperweight's arguments. FAKE_PAPERWEIGHT_PLAN (JSON) maps a paper id
(the --file stem) to a mode; FAKE_PAPERWEIGHT_LOG names a directory that gets
one JSON file per invocation.

- ok: run the --prompt it was given through the Lua shim and write the report,
  which carries the diagnostics appendix only if that prompt asks for it.
- missing: as ok, with a grader that drops a share of replies.
- exit1: print an error and exit 1, writing nothing.
- garbage: exit 0 with a report that is not paperweight's format.
- noappendix: exit 0 with a well-formed report and no diagnostics.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import uuid
from pathlib import Path

from calibrate import shim, simulate


def main() -> int:
    if sys.argv[1:] == ["--version"]:
        sys.stdout.write("paperweight 0.0.0-fake\n")
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--model")
    args = parser.parse_args()
    if not (os.environ.get("RUNVIL_GATEWAY_URL") and os.environ.get("RUNVIL_GATEWAY_API_KEY")):
        sys.stderr.write("error: RUNVIL_GATEWAY_URL and RUNVIL_GATEWAY_API_KEY must both be set\n")
        return 1
    paper = args.file.stem
    plan = json.loads(os.environ.get("FAKE_PAPERWEIGHT_PLAN", "{}"))
    mode = plan.get(paper, "ok")
    # One file per invocation: parallel runs appending to one shared file can
    # lose a line on Windows.
    record = Path(os.environ["FAKE_PAPERWEIGHT_LOG"]) / f"{paper}-{uuid.uuid4().hex}.json"
    record.write_text(json.dumps({"paper": paper, "mode": mode, "prompt": str(args.prompt),
                                  "model": args.model}), encoding="utf-8")
    sys.stderr.write("[paperweight] Assess: start\n")
    if mode == "exit1":
        sys.stderr.write("error: run failed: the gateway refused the request\n")
        return 1
    if mode == "garbage":
        args.output.write_text("this is not a paperweight report\n", encoding="utf-8")
        return 0
    if mode == "noappendix":
        args.output.write_text("Weight: Medium (6/14)\n\nProse.\n", encoding="utf-8")
        return 0
    profile = simulate.PROFILES["calibrated"]
    if mode == "missing":
        profile = dataclasses.replace(profile, missing_rate=0.2)
    grader = simulate.SimulatedGrader(profile, truth_seed=1, noise_seed=2)
    prompt = args.prompt.read_bytes().decode("utf-8")
    run = shim.run_paper(prompt, args.file.read_bytes().decode("utf-8"), grader, paper_id=paper)
    args.output.write_bytes(run.report.encode("utf-8"))
    sys.stdout.write(f"{args.output}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
