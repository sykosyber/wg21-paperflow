# Paperweight Calibration Harness: spec

Oct 26, 2026 · @mateo

The harness reruns paperweight on a fixed set of human-graded papers whenever its prompt changes, and reports how far the grades moved from the reviewers and from the last accepted version.

## Context

The aggregation rules in [paperweight.md](https://github.com/cppalliance/wg21-paperflow/blob/master/crates/paperweight/paperweight.md) were tuned by hand. Its comments record each experiment's numbers against ten calibration papers graded by three human reviewers:

| Change recorded in the prompt | Measured effect |
| --- | --- |
| Corroboration across sections instead of a plain max | Bias +2.43 to +0.93, MAE 3.03 to 1.73, correlation 0.70 to 0.87 |
| Adjudication turn (since removed) | Bias +2.53 to -2.27, correlation 0.68 to 0.53; it awarded 2 in 10 of 70 judgements where reviewers did in 30 |
| Run-to-run stability, two full runs | Same exact total 1 in 10, same integer 5 in 10, same band 9 in 10; sigma of the total 0.41 points |
| Band span on the verdict line | Reproduces 8 in 10; 10 of 10 run pairs nested, never contradictory |

Those numbers came from runs and scripts that are not in the repo, so the next change to a criterion, a threshold or the Grade prose can't be checked the same way. The calibration papers and reviewer grades are not in the repo either.

The pieces the harness builds on already exist:

- `paperweight --file <paper.md> --output <report.md> --prompt <path> --model <id>` runs one paper through a Runvil gateway ([lib.rs](https://github.com/cppalliance/wg21-paperflow/blob/master/crates/paperweight/src/lib.rs)).
- The `tests.yml` workflow already builds the binary and uploads it as the `paperweight-linux-x86_64` artifact.
- The prompt already writes `diagnostics.md` with per-section votes, the totals under all four inter-section rules and the single-sample totals. Its epilogue keeps a commented-out block that appends them to the report.
- `packages/assay` has the house pattern for this kind of work: a golden set under `data/golden/` with a README, and evaluation scripts under `scripts/`.

## Goals and non-goals

The harness succeeds when anyone who edits paperweight.md can see, before merging, whether the change moved the grades toward the reviewers or away from them, and by more than run-to-run noise.

**Goals**

1. Reproduce the numbers in the prompt's comments with one command, from files in the repo.
2. Compare any prompt version to a baseline: per criterion, per paper and in total.
3. Evaluate changes to the Lua aggregation (rules, thresholds, bands) with no model calls, by replaying recorded votes.
4. Run in CI on demand, and post the comparison on the pull request.
5. Keep a history of every accepted calibration run, so drift in the model or the gateway shows up even when the prompt has not changed.
6. Work with any model the gateway lists, so models can be compared on the same set.

**Non-goals**

- Changing paperweight's output or the deployed reports on wg21.org.
- Tuning the prompt automatically. The harness measures; a person decides.
- Grading papers outside the calibration set, or replacing human review.
- A general eval framework for every paperflow pipeline. It can grow into one later; this spec covers paperweight.

## How it works

Every change to the prompt gets scored against the same human grades and compared with the last accepted run; the mode decides whether that costs model calls.

```text
Prompt change (a PR to paperweight.md)
  -> Only the epilogue Lua changed?
       yes -> Replay recorded votes (no model calls, every push)
       no  -> Full run (papers x repeats, on a label)
  -> Score (agreement and stability metrics)  <- Golden set (10 papers, 3 reviewers)
  -> Compare to baseline (gates fail the job; readings inform)  <- Baseline (last accepted run, per model)
  -> Comment on the PR (author decides)
  -> on merge, the run becomes the baseline
```

A change confined to the epilogue's arithmetic is replayed on recorded votes in seconds. Any change to what the graders read needs a full run, triggered by a label.

## The calibration set

The set is the ten papers and three reviewers' grades the prompt was tuned on, checked in with each paper's markdown pinned by hash, so a change to tomd can't silently change the inputs.

**Files, under `packages/calibrate/data/golden/`**

| File | Holds |
| --- | --- |
| `README.md` | Where the papers and grades came from, who the reviewers are (or their initials), and the labeling rules, as `assay`'s golden README does |
| `papers.jsonl` | One line per paper: `paper` (e.g. `P3643R3`), `markdown_sha256`, `tomd_version`, `split` (`calibration` or `holdout`) |
| `papers/<paper>.md` | The exact markdown each reviewer graded against |
| `grades.csv` | One row per paper, reviewer and criterion: `paper,reviewer,criterion,grade` with `grade` in 0, 1, 2 |

Criteria use the prompt's internal `short` names (`motivation`, `audience`, `prior_art`, `vehicle`, `coordination`, `insufficiency`, `implementation`). The loader rejects a row whose criterion is not in the prompt's `CRITERIA` table, so renaming a criterion fails loudly instead of silently dropping its grades.

**Derived per paper:** the reviewer mean per criterion, the reviewer mean total (0 to 14), and the band of that total under the prompt's `LABELS`.

**A holdout, once there are more grades.** Ten papers are what the rules were tuned on, so every number on them is in-sample. When more papers are graded, they go in as `holdout` and are reported separately; a change that helps calibration but hurts holdout is overfitting.

## Two modes

A full run calls the model and is needed for any change to what the graders read; a replay recomputes the verdict from recorded votes and is enough for a change to how votes are combined.

### Full run

Runs the `paperweight` binary on every paper in the set, `repeats` times each (default 3), with the candidate prompt and one model.

- **Getting the votes out.** The harness needs `diagnostics.md`, which the prompt keeps in the store. Preferred: a small upstream change so the epilogue appends the diagnostics block when `--args` contains `diagnostics`; the deployed reports stay unchanged. Until then, the harness passes a copy of the prompt with the commented appendix restored, via `--prompt`, and records that it did.
- **What it records per run:** the report, the parsed diagnostics, the per-criterion grades, the total, the label line, the model id, the prompt's sha256, the paperweight binary's version and the wall time.
- **Concurrency.** Papers run in parallel up to `--jobs` (default 4); repeats of one paper run one after another, so a rate limit hits evenly.
- **Failures.** A run that exits non-zero, or whose diagnostics report missing replies, is kept and counted, never retried silently. Its paper is marked incomplete for that repeat.

### Replay

Recomputes every criterion grade, the total and the label from the per-section votes in a recorded run's diagnostics, with no model call. It answers "what would this aggregation change have done to the last full run?", which is how the corroboration and adjudication numbers in the prompt were simulated.

- **What replay can evaluate:** `INTER_RULE`, `CORROBORATION`, `STRONG`, `ACCUM_FULL`, the `BINARY` set, `LABELS`, `EDGE_WINDOW` and the band-span rule.
- **What it can't:** criterion text, guidance, the Grade or Assess prose, sectioning, `SAMPLES`, quote validation, triage. Those change the votes themselves, so they need a full run.
- **Choosing the mode.** The harness diffs the candidate prompt against the baseline. If every changed line is inside the Assess epilogue's Lua block, replay is offered; otherwise a full run is required. `--mode full` can always be forced.
- **Parity, the load-bearing test.** Replay reimplements the epilogue's arithmetic in Python. For every recorded run, the Python totals under all four inter-section rules must equal the totals the prompt itself printed in `Totals under every inter-section rule:`, to the two decimals it prints. Any mismatch fails the harness's own tests.
- **Later.** Replaying through Runvil itself, with the recorded model replies scripted back through the Harness, would remove the Python copy. That needs the scripted Host from the Attest CLI runner spec, so it waits until that exists.

## Metrics

The harness computes the same numbers the prompt's comments already use, so a new run can be read against the old ones, plus the reviewers' agreement with each other as the ceiling.

**Agreement with the reviewers** (against the reviewer mean, per paper)

| Metric | Definition | Recorded in the prompt |
| --- | --- | --- |
| Bias | Mean of (paperweight total minus reviewer mean total) | +0.93 after corroboration |
| MAE | Mean absolute difference of the totals | 1.73 |
| Correlation | Pearson r between paperweight totals and reviewer mean totals | 0.87 |
| Reviewer ceiling | Mean pairwise Pearson r between the three reviewers' totals | "above the reviewers' agreement with each other" |
| Per-criterion bias | Bias for each criterion on its 0 to 2 scale | Prior art "most often over-graded"; insufficiency "graded 0 far more often" |
| Grade-2 rate | How often paperweight and the reviewers award 2, per criterion | Adjudication: 10 of 70 against 30 |
| Band agreement | Share of papers where the band matches the reviewers' band | Not recorded |

**Stability across repeats** (same prompt, same model, same paper)

| Metric | Definition | Recorded in the prompt |
| --- | --- | --- |
| Sigma of the total | Standard deviation of the total across repeats, averaged over papers | 0.41 points |
| Same exact, integer, band | Share of repeat pairs that print the same exact total, rounded total, band | 1, 5 and 9 in 10 |
| Band-span nesting | Share of repeat pairs whose label spans are equal or nested | 10 of 10 |
| Sample agreement | Share of section-criterion triples where all three samples agree, from diagnostics | Printed per run |

**Health counters:** unsupported quotes rejected, replies missing, papers triaged `NOT_PROPOSAL`, runs failed, wall time, and model calls.

**Uncertainty.** With ten papers, one paper moves the correlation a lot. Every agreement metric carries a 95% bootstrap interval over papers (2,000 resamples, fixed seed), and comparisons between two versions are paired by paper.

## Verdict: what gates and what informs

Only yes/no properties fail the job; the agreement numbers are reported with a reading, and the author decides. This follows Runvil's rule to gate on yes/no properties, never on a score threshold that ordinary work edits.

**Gates: any one fails the job**

1. Every run exits 0 and its report starts with a `Weight:` line the prompt's own format would produce.
2. No run reports missing replies.
3. Every criterion in `grades.csv` is still in the prompt's `CRITERIA`, and the reverse.
4. Replay parity holds on every recorded run.

Band-span nesting across repeats is reported and flagged, not gated. The prompt measured it at 10 of 10, but it is an observed rate, and a gate on a sampled property would fail at random.

**Reading: reported on every comparison, never failing the job**

For MAE, bias and correlation, the harness takes the paired difference between candidate and baseline over the same papers, with its bootstrap interval:

| Reading | When |
| --- | --- |
| better | The interval lies entirely on the improving side |
| within noise | The interval includes zero |
| worse | The interval lies entirely on the worsening side |

The comment also lists each paper whose band changed, with the reviewers' band beside it, because a band flip is what a reader of the report on wg21.org sees.

**Baseline.** The last calibration run accepted on `master`, by prompt sha256 and model. A run on a different model compares against that model's baseline, or reports "no baseline" and serves as one.

## Interface

Four commands, one workflow and one pull request comment.

**Commands** (`uv run calibrate <verb>`)

| Verb | Does | Model calls |
| --- | --- | --- |
| `full --prompt <path> --model <id> [--repeats 3] [--jobs 4]` | Runs the set and writes a run folder | Yes |
| `replay --prompt <path> --from <run>` | Re-aggregates a recorded run under the candidate's epilogue | None |
| `compare <candidate run> <baseline run>` | Prints the gates, the readings and the band changes | None |
| `report <run>` | Writes `summary.md` and `summary.json` for one run | None |

The binary comes from `PAPERWEIGHT_BIN` or `PATH`; the gateway from `RUNVIL_GATEWAY_URL` and `RUNVIL_GATEWAY_API_KEY`, as paperweight already reads them. Nothing is written outside the run folder.

**Workflow, `.github/workflows/calibrate.yml`**

- **On a pull request that touches `crates/paperweight/paperweight.md`:** if replay is eligible, replay against the baseline run and comment. That costs no model calls, so it runs on every push. Otherwise, comment that a full run is needed.
- **On the `calibrate` label, or a manual dispatch:** a full run with the `paperweight-linux-x86_64` artifact from `tests.yml`, then a comparison and a comment. The label is limited to maintainers, because the gateway key is a repository secret and fork pull requests can't read it anyway.
- **On merge to `master`:** the PR's accepted run is recorded as the new baseline, appended to `history.jsonl` on a separate `calibration` branch, so CI never needs to push to `master`.

**The comment**

````markdown
### Paperweight calibration · full run · 10 papers × 3 repeats · model qwen3
Gates: 4 of 4 pass

| Metric | Baseline | Candidate | Difference (95% interval) | Reading |
| --- | --- | --- | --- | --- |
| MAE | 1.73 | 1.51 | -0.22 (-0.61 to +0.12) | within noise |
| Bias | +0.93 | +0.40 | -0.53 (-0.90 to -0.18) | better |
| Correlation | 0.87 | 0.88 | +0.01 (-0.05 to +0.07) | within noise |

Bands changed: P3643R3 Heavy to Medium (reviewers: Medium)
Stability: sigma 0.38, same band 9 of 10, spans nested 30 of 30
````

The numbers in that block are made up to show the layout.

## Cost and budget

A full calibration is a few thousand model calls, so it runs on a label, not on every push; a replay costs nothing and does.

Per paper, paperweight makes one triage call, one Grade call per criterion, section and sample, and one Analyze call: 2 + 7 × sections × 3. The prompt's comments give the section counts across the paper store:

| Paper size | Sections | Calls per run | 10 papers × 3 repeats |
| --- | --- | --- | --- |
| p25 | 5 | 107 | 3,210 |
| Median | 8 | 170 | 5,100 |
| p75 | 11 | 233 | 6,990 |

Each Grade call carries one section (at most `SECTION_BUDGET`, 30,000 characters) plus the criterion text, so input tokens dominate. Dollar cost depends on the model the gateway binds, so the harness prints calls, tokens (when the gateway reports usage) and wall time on every run, rather than estimating money.

**Levers:** `--repeats 2` halves the cost but gives a weaker sigma. `--papers` runs a subset for a quick check, and its comment says it is partial. A local model behind the gateway makes full runs free apart from time.

## Where it lives

A new uv workspace package in wg21-paperflow, `packages/calibrate`, beside `assay`. It is Python, calls the `paperweight` binary as a subprocess, and imports nothing from the Rust crates.

```text
packages/calibrate/
  pyproject.toml
  src/calibrate/
    CLAUDE.md          package rules, as the other packages have
    __main__.py        the four verbs
    golden.py          load and validate papers.jsonl and grades.csv
    run.py             full runs: subprocess, concurrency, run folder
    diagnostics.py     parse diagnostics.md into votes, grades and totals
    aggregate.py       the epilogue's arithmetic, for replay
    metrics.py         agreement, stability, bootstrap, paired differences
    compare.py         gates, readings, band changes, the comment
  data/golden/         README.md, papers.jsonl, papers/, grades.csv
  tests/
    fixtures/          recorded diagnostics from real runs
    test_parity.py     aggregate.py against every fixture
    test_metrics.py    known inputs, known outputs
    test_golden.py     criteria match the prompt's CRITERIA
```

A run folder is `calibration-runs/<date>-<prompt sha8>-<model>/`, holding `meta.json`, one `<paper>.r<n>/` per run with the report and diagnostics, and `summary.json`. It is uploaded as a CI artifact, and it is git-ignored on `master`.

## Milestones and acceptance

Six milestones; the first two need no golden data, so work can start before Vinnie sends the grades.

1. **Diagnostics parser and replay.** `diagnostics.py` and `aggregate.py`, tested against recorded diagnostics. Done when parity holds on every fixture under all four rules. Fixtures come from existing runs if the team has them, or from a few real runs.
2. **Metrics.** `metrics.py` with known-answer tests: hand-computed bias, MAE, r and bootstrap intervals on small synthetic sets, with a fixed seed. Done when the tests pin every metric in the tables above.
3. **Golden set.** `papers.jsonl`, `papers/`, `grades.csv` and the README, with the loader and its criteria check. Done when the ten papers and all 210 grades (10 papers × 3 reviewers × 7 criteria) load.
4. **Full runner.** `calibrate full` with run folders, concurrency and failure accounting. Done when one full run of the set completes with every gate passing.
5. **Reproduce the record.** Run the current prompt with the model the team tuned on. Done when bias, MAE and correlation land inside their bootstrap intervals around the values in the prompt's comments, or the gap is explained in writing.
6. **CI and comments.** `calibrate.yml`, the label, the comment and the baseline history on the `calibration` branch. Done when a test pull request gets both a replay comment and a full-run comment.

**Acceptance for the whole spec:** a pull request that changes `INTER_RULE` from `top2` to `max` gets a comment within minutes, with no model calls, showing the bias moving up. That is the direction the prompt's comments recorded when corroboration replaced the plain max.

## Risks and open questions

The harness depends on data only the team has; the main technical risk is the Python copy of the aggregation drifting from the Lua.

**Risks**

- **Ten papers is a small sample.** Intervals will be wide, and most changes will read "within noise". That is the honest reading, and the holdout split is how the set grows.
- **Overfitting the set.** Every rule was tuned on these ten papers, so a run on them overstates quality. Holdout numbers are reported separately once they exist.
- **Replay drift.** If the epilogue changes in a way `aggregate.py` doesn't model, parity fails. That is the intended behaviour: the harness refuses to replay rather than report a wrong number.
- **Model and gateway drift.** A new model build can move grades with no prompt change. History by model and date shows it; an optional weekly run on `master` would catch it sooner, at full-run cost.
- **Input drift.** A tomd change alters paper markdown. The set pins the markdown by hash, so calibration inputs only change on purpose.

**Open questions for Vinnie**

- [ ] Can the ten papers and the three reviewers' per-criterion grades be checked in, and can the reviewers be named or should they be initials?
- [ ] Are the scripts and runs behind the numbers in the prompt's comments available? They would give milestone 1 its fixtures and milestone 5 its target.
- [ ] Which model and gateway setup produced those numbers?
- [ ] Would he accept the small epilogue change that appends diagnostics when `--args` asks for them?
- [ ] Is there a monthly budget for full calibration runs, or a local model to run them on?
- [ ] Should this live in wg21-paperflow as `packages/calibrate`, or does he want it as a Runvil prompt or Host, closer to the 15% code / 85% prose direction?
