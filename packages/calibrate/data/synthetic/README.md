SYNTHETIC: this calibration set is generated. The papers are real; every grade is simulated. Nothing measured on it is a finding about paperweight.

# Synthetic calibration set

A stand-in for the real golden set until the team's papers and grades arrive.
It has the golden set's layout and schema, so the whole harness runs on it, but
SYNTHETIC is written on every file: `"synthetic": true` on every line of the
JSONL files, and a first line starting with `SYNTHETIC` in this README and in
`grades.csv`. The loader refuses to mix it with golden data, and every report
built on it starts with `SYNTHETIC`.

Regenerate it with:

```bash
uv run python packages/calibrate/scripts/make_synthetic_set.py
```

Generation is deterministic: the same prompt and the same papers give the same
bytes. It was generated against the prompt with sha256
`8b903808b5c56054d7cc6311d44c07ba427661527f3c111c92542d9bb7f8bd03` (CRLF read as LF).

## Files

| File | Holds |
| --- | --- |
| `papers.jsonl` | One line per paper: `paper`, `markdown_sha256`, `tomd_version`, `split`, `synthetic`, and `source`, the fixture it was copied from |
| `papers/<paper>.md` | The paper markdown, byte for byte as git stores the tomd fixture |
| `grades.csv` | `paper,reviewer,criterion,grade` after the `SYNTHETIC` line, one row per paper, reviewer and criterion |
| `truth.jsonl` | The latent truth both the reviewers and the simulated grader are drawn around, with the sections that carry it |

## Papers

The papers are real: the tomd golden fixtures in
`packages/tomd/tests/fixtures/golden/ideals/` that the shim's triage stub calls
proposals (a P-number, and no informational `intent`), copied with LF line
endings and pinned by sha256. They are not the ten papers the prompt was tuned
on, which are not in the repository. They carry no SYNTHETIC line, because
any added line would change what the prompt reads; this README and
`papers.jsonl` mark them.

Sorted by paper number, the first 10 are `calibration`: P0533R9, P0957R8, P1068R11, P1122R3, P2040R0, P3290R4, P3411R5, P3556R0, P3953R0, P3978R0.
The rest are `holdout`: P4020R0, P4228R0.

`tomd_version` is the tomd package version in the workspace when the set was
built, not the version that produced the fixtures, which is not recorded.

## How the grades were drawn

1. **Units.** The prompt's own Assess prologue, run by the shim, splits each
   paper into units. A unit is *argument* unless its heading names bookkeeping
   (changelog, revision, history, acknowledgements, thanks, references,
   bibliography, wording, polls, minutes) or it has no line of three or more
   words to quote.
2. **Latent truth**, seed `TRUTH_SEED = 20261026`. Each paper and criterion
   draws a grade from a per-criterion prior. A grade of 2 is carried by two
   argument units at 2; a grade of 1 by one unit at 2 or two units at 1 (even
   odds); `implementation` by one unit at its grade. The truth is what the
   prompt's current aggregation (mean of the two best units, the max for
   `implementation`) makes of those unit grades, which is the drawn grade
   unless the paper has too few argument units.
3. **Reviewers**, seed `REVIEWER_SEED = 1026`. Each reviewer has an
   overall lean; each criterion gets its own lean drawn from a normal around it
   with the spread below; each grade adds normal noise and is rounded half up
   and clamped to 0..2.

| Criterion | P(0) | P(1) | P(2) |
| --- | --- | --- | --- |
| `motivation` | 0.05 | 0.45 | 0.50 |
| `audience` | 0.55 | 0.30 | 0.15 |
| `prior_art` | 0.02 | 0.48 | 0.50 |
| `vehicle` | 0.35 | 0.45 | 0.20 |
| `coordination` | 0.50 | 0.35 | 0.15 |
| `insufficiency` | 0.70 | 0.22 | 0.08 |
| `implementation` | 0.25 | 0.25 | 0.50 |

| Reviewer | Lean | Per-criterion spread | Noise sigma |
| --- | --- | --- | --- |
| `SYN-A` | -0.15 | 0.15 | 0.35 |
| `SYN-B` | +0.00 | 0.15 | 0.30 |
| `SYN-C` | +0.20 | 0.15 | 0.40 |

Every draw uses its own `random.Random`, seeded with a string naming the seed,
the purpose and the coordinates, for example `"1026|noise|SYN-A|P0533R9|motivation"`.
The simulated grader (`calibrate.simulate`) uses the same truth seed, so a
calibrated grader and these reviewers agree in expectation, and every
difference a run shows is the simulation's noise and bias, not paperweight's.
