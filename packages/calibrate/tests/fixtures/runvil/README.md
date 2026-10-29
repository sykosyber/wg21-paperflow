# Recorded runs of the real engine

Unlike everything under `../synthetic/`, these are real paperweight runs: the
`paperweight` binary, through a Runvil gateway, with every Grade vote, the
triage and the Analyze prose written by a model. They are kept to check that
the harness agrees with the real engine, not just with its own shim.

| Run | What it was |
| --- | --- |
| `P3953R0-gpt-6-luna` | P3953R0 (from tomd's golden fixtures), once, on 2026-10-27. Model `gpt-6-luna` with reasoning off (`reasoning_effort: "none"`), reached through `runvil-gateway` 0.3.0 and `calibrate.openai_proxy`. A debug build of `paperweight` 0.1.0, given the harness's diagnostics patch. 128 model calls, none failed, two quotes rejected. |

Each run is stored as paperweight wrote it: `.report.md` with the diagnostics
appendix, and `.diagnostics.md` as cut from that appendix. `index.jsonl` keeps
the paper's and the prompt's sha256 and the epilogue constants in force.

`test_runvil_parity.py` checks two things on each run. The Python arithmetic
must reproduce every number the real Lua printed. And the shim must split the
paper into the same sections the real engine did.

A model's grades are not a measure of paperweight's quality here: there are no
reviewer grades for these papers, only the run itself.
