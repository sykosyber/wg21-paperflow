# Calibration harness: status

Oct 26, 2026 · companion to [calibration-harness.md](calibration-harness.md)

The harness is built end to end and tested, but every number it has produced
so far is synthetic. The real calibration set, a model gateway and a real
paperweight run are still missing, so nothing here says anything yet about how
well paperweight agrees with its reviewers.

## What is real, what is simulated

| Part | Status |
| --- | --- |
| paperweight.md's Lua | **Real.** The shim runs the prompt's own seven Lua blocks, unmodified, under Lua 5.5 (`lupa.lua55`). Only the model turns are stubbed. |
| Diagnostics parser, replay arithmetic | **Real.** `aggregate.py` reproduces every number the Lua printed, to the character, on 51 recorded runs and on live shim runs under all four inter-section rules. |
| Metrics, bootstrap, gates, readings, comment | **Real.** Known-answer tests on hand-computed sets; planted truth recovered through the whole pipeline. |
| Runner, `binary` backend | **Real, one paper once.** Tested against a fake binary on `PATH`, and run once for real on 2026-10-27 (see "The real-engine smoke test" below). |
| CI workflow | **Real, partly exercised.** The replay job runs on the fork's draft pull request against the synthetic baseline. The full-run job has only been seen to skip, because no gateway secret is set. |
| Grade votes, triage, Analyze prose | **Simulated.** `simulate.py`, a seeded grader drawn around a latent truth, and two fixed stubs. |
| Reviewer grades | **Simulated.** `data/synthetic/grades.csv`: three simulated reviewers on real tomd fixture papers. |
| Papers | **Real WG21 markdown,** from tomd's golden fixtures. They are not the ten papers the prompt was tuned on. |
| Baseline history | **Synthetic only.** The `calibration` branch of the fork holds one synthetic baseline under `synthetic/`. |
| Example comment | **Synthetic.** `packages/calibrate/examples/synthetic-comment.md`. |

## The real-engine smoke test (step M)

Step M ran on 2026-10-27, with the user's go-ahead, on exactly one paper once: P3953R0 through the real `paperweight` binary, a local `runvil-gateway` and OpenAI's `gpt-6-luna`. It took 128 model calls and 22 seconds, with no failures and no missing replies. The epilogue's quote check rejected two quotes. All four gates passed.

What it established:

- **Parity holds against the real engine.** `aggregate.py` reproduces every total, grade, provisional line and verdict line the real Lua printed, not only the shim's.
- **The shim sections the paper exactly as the engine does**, with the same six units and titles.
- **The diagnostics patch works end to end.** The appendix came back through the real binary and parsed cleanly.

The run is kept as `packages/calibrate/tests/fixtures/runvil/P3953R0-gpt-6-luna`, and `test_runvil_parity.py` checks it on every test run. Its grades say nothing about paperweight's quality: the synthetic set has no real reviewer grades for P3953R0.

How it was wired, so the next run can repeat it:

- **OpenAI needs a translating proxy.** Runvil's client speaks the convention of self-hosted servers. OpenAI's reasoning models reject all three of the fields that matter: `chat_template_kwargs` (unknown), `max_tokens` (renamed `max_completion_tokens`), and `temperature = 0.3` unless `reasoning_effort` is `"none"`. `calibrate.openai_proxy` rewrites only those fields, holds the API key, and passes responses through untouched. `packages/calibrate/gateway/openai-luna.toml` is the gateway config that uses it. A self-hosted vLLM or llama.cpp model needs no proxy.
- **Building on this Windows machine** needed two workarounds outside the repo. The `windows-gnu` toolchain must link with a full MinGW GCC (WinLibs), because the llvm-mingw first on `PATH` lacks `libgcc`. And the gateway's settings UI needs `npm ci` in `vendor/runvil/crates/gateway/config-ui/ui` before `cargo build`.
- **Port 8090 is taken on this machine**, so the proxy defaults to 18090. The gateway uses 8081.

## The first full run on a real model

Run on 2026-10-27 with the user's go-ahead: all 12 papers of the synthetic set × 3 repeats, through the real `paperweight` binary and `gpt-6-luna` (reasoning off), with the proxy capped at 8,000 requests. It took 6,351 model calls in 7 minutes 23 seconds, about 10M input tokens, roughly $1.10 at list price. No run failed and no reply went missing, all four gates pass, and parity holds on all 36 runs. It is recorded under `synthetic/` on the `calibration` branch: the votes are real model output, but the grades it is scored against are not.

Real observations about paperweight on this model. They need no reviewer grades, but they are about `gpt-6-luna`, not about the model the prompt was tuned on:

| Measure | This run (8 papers, 24 repeat pairs) | Recorded in paperweight.md |
| --- | --- | --- |
| Sigma of the total | 0.49 | 0.41 |
| Same band | 20 of 24 | 9 of 10 |
| Same integer total | 11 of 24 | 5 of 10 |
| Same exact total | 2 of 24 | 1 of 10 |
| Band spans nested | 22 of 24 | 10 of 10, "never contradictory" |

- **The span claim does not hold on this model.** P2040R0's repeats read Heavy, then Medium, then Medium. That is a contradictory pair, not a nested one.
- **Triage flips between repeats.** P3411R5 was called not a proposal in 2 of 3 repeats, and P3556R0 in 1 of 3. Each flip turns a full verdict into `Weight: n/a`. P4020R0, a position paper, was called not a proposal every time, which is defensible. The harness now flags a paper whose triage disagrees between repeats, in the report's health line and the comment, and leaves it out of the accuracy numbers with that reason.
- **The quote check rejects real paraphrases.** 315 quotes were rejected across the 36 runs, about 5% of Grade calls.
- **Full marks cluster on two criteria.** `motivation` got grade 2 in 22 of 24 judgements and `prior_art` in 17. `vehicle`, `coordination` and `insufficiency` never got it.

The run's bias, MAE and correlation, and every per-criterion bias, are measured against synthetic grades. They mean nothing and are not reported here.

## Proxy study: ICLR 2025 reviewers

To test the harness's statistics on real human disagreement before the golden set arrives, `scripts/iclr_reviewer_study.py` runs them on ICLR 2025's public reviews. That's 11,521 papers, each with reviewer scores for soundness, presentation and contribution from 1 to 4. No model is called. The full results are in `packages/calibrate/studies/iclr-2025-reviewers.md`. Its data is real but its rubric is not paperweight's, so it is marked PROXY, and nothing in it is a finding about paperweight.

What it says about the harness, read with the paired permutation test the harness now uses:

- **Ten papers detect only large improvements, and rarely.** A real improvement that cuts the error by about 19% (the mean of two reviewers instead of one) reads "better" 8% of the time on 10 papers, 39% on 40 and 70% on 80. One that cuts it by about 25% reads "better" 14% of the time on 10 papers and 87% on 80. Most genuine prompt improvements will read "within noise" on the ten calibration papers. Grading about 40 to 80 papers is what makes readings informative.
- **The bootstrap interval the harness first read from was too narrow on ten papers, and it has been replaced.** Swapping one reviewer for another, which is no change, read as significant 12% of the time on 10 papers, against a nominal 5%. The readings now come from a paired permutation test (`metrics.paired_permutation`, exact up to 12 papers). Its false-alarm rate on the same draws is 4% on 10 papers and 2% to 4% elsewhere. The interval is still shown beside each difference. This departs from the spec, which read the verdict from the interval.
- **ICLR reviewers agree weakly:** the reviewer ceiling is 0.24, and a single reviewer reaches r = 0.32 against the others' mean. WG21 reviewers on paperweight's rubric may agree far more; the paperweight.md comments put its agreement above theirs at r = 0.87. So the sample-size numbers above carry over only roughly, and the golden set will give the real ones.

The data is Paper Copilot's public list, pinned by sha256. Its repository declares no license, so it is downloaded locally and never committed. The list orders each paper's reviews by overall rating, so the study shuffles reviewers per paper, with a seed, before computing anything. The unshuffled version was skewed, and its numbers were thrown away.

## Where the shim and the real Runvil could differ

The shim module docstring keeps the full list. In short:

- **Engine globals.** Only `store` (read and write), `models`, `tasks.fanout`, `untrusted`, `var`, `args`, `item` and `prose` exist. A prompt that starts using any other Engine global fails in the shim first.
- **Engine limits.** No memory, response or time limits apply, and fanout runs serially in job order instead of up to 8 at a time.
- **`untrusted`.** It returns its input unchanged instead of wrapping it in nonce delimiters, so the prose a model would see differs. No Lua arithmetic depends on it.
- **Templates.** Rendering is plain `{{ var.x }}` substitution, and there is one `var` table per section run.
- **Fanout return value.** It is an empty table, not a host object, so the epilogue's `as_string(replies[i])` fallback never supplies a reply.
- **Harness.** No Harness, gateway, model binding, `models.use` options, recorder or cancellation.
- **Invalid UTF-8.** Lua slices strings by byte, and the shim decodes the store with replacement characters.

## Blocked on data from Vinnie

- The ten calibration papers and the three reviewers' per-criterion grades (milestone 3 with real data, and everything after it).
- The scripts and runs behind the numbers in the prompt's comments. Their diagnostics would be real parity fixtures, and their numbers milestone 5's target.
- The model and gateway the numbers came from, and a budget or a local model for full runs.

## Swapping in the golden set

1. Put each paper's exact markdown, the bytes the reviewers graded, in `packages/calibrate/data/golden/papers/<paper>.md`. Line endings are kept as committed (`-text`), so commit them exactly.
2. Write `packages/calibrate/data/golden/papers.jsonl`, one line per paper: `{"paper": "P3643R3", "markdown_sha256": "<sha256 of the file>", "tomd_version": "<version>", "split": "calibration"}`. Leave out the `synthetic` field. Papers graded later go in as `"split": "holdout"`.
3. Write `packages/calibrate/data/golden/grades.csv`: the header `paper,reviewer,criterion,grade`, then one row per paper, reviewer and criterion, using the prompt's `short` names.
4. Add provenance, reviewer names or initials, and the labeling rules to `data/golden/README.md`. Keep its first line free of the word SYNTHETIC.
5. Run `uv run calibrate check-set`. It must report a golden set, ten calibration papers and 210 grades, and that the criteria match the prompt.
6. On the repository: set the variable `CALIBRATE_MODEL` to the gateway model id, and add the secrets `RUNVIL_GATEWAY_URL` and `RUNVIL_GATEWAY_API_KEY`.
7. Make the first real baseline. One way is a manual dispatch of the `calibrate` workflow. The other is local:
   ```bash
   uv run calibrate full --backend binary --model <id>
   uv run calibrate record <run> --history <calibration branch checkout>
   ```
   Commit and push that checkout to `calibration`.
8. Milestone 5: compare that run's `summary.md` with the bias, MAE and correlation in the prompt's comments, and explain any gap in writing.

The synthetic set stays: the tests use it, and the replay job falls back to it only while no real baseline exists for `CALIBRATE_MODEL`. Real lookups never read the synthetic history.

## Readings of the spec, taken conservatively

Where the spec was silent or ambiguous, I took the reading below and wrote it down here.

- **Lua version.** The brief said to use `lupa.lua54` to match Runvil's Lua 5.4. The vendored Runvil links Lua 5.5 (mlua `lua55`, `lua-src` 550.1.1), so the shim uses 5.5. A test runs a paper under 5.4 and gets the same store for this prompt.
- **When replay is allowed.** It is stricter than the spec. Every changed line must sit inside the Assess epilogue, *and* the epilogues may differ only in `INTER_RULE`, `CORROBORATION`, `STRONG`, `ACCUM_FULL`, `EDGE_WINDOW`, `BINARY` and `LABELS`. Anything else needs a full run: an edit to a comment on one of those lines, a change to `QUOTE_WORDS`, or a change to the arithmetic or to `band_span` itself.
- **A paper's total.** The mean of its completed (status ok) repeats. Metrics read the numbers as printed, to two decimals, so a full run and a replay of it score identically.
- **Bands.** Both paperweight's and the reviewers' bands are `label_for(round half up(total))`, under the run's own `LABELS`, as the verdict line does it.
- **Grade-2 rate.** It counts judgements at exactly 2, one per completed repeat. Under `top2` a grade can be 1.83, which is not full marks.
- **Sigma.** The sample standard deviation of a paper's totals across repeats, averaged over papers with at least two completed repeats.
- **Bootstrap.** Nearest-rank 2.5% and 97.5% of 2,000 resamples over papers, with seed 20261026. A resample on which a statistic is undefined is dropped and counted.
- **Bias reading.** "Better" means a smaller absolute bias, so the reading uses the paired difference of |bias|. The table shows the signed difference, as the spec's example does.
- **Failed and incomplete runs.** They are kept and counted, fail gates 1 and 2, and are left out of the agreement metrics. NOT_PROPOSAL papers are left out of agreement and counted.
- **Comparisons refused.** A synthetic run is never compared with a real one, in either direction. Runs on different models are not compared, since the spec gives each model its own baseline.
- **Baselines.** Only full, non-partial runs can be baselines, because replay needs recorded votes. Replays are still recorded in the history, for drift.
- **Recording on merge.** The record job runs on a push to `master` that changes the prompt, not on the pull request closing, because a fork's pull request gets a read-only token.
- **Full runs without real grades.** The full-run job skips, with a notice, while the golden set is absent, rather than spend model calls on synthetic grades.
- **Shim output.** A shim run's `report.md` and `diagnostics.md` start with a SYNTHETIC line. The `Weight:` gate reads the line after it, and only in a run whose metadata says synthetic.
- **Unmarked synthetic papers.** The papers in `data/synthetic/papers/` carry no SYNTHETIC line, because a line would change what the prompt reads. The README and every `papers.jsonl` line mark the set.
- **Paths and hashes.** Prompts are hashed and parsed with CRLF read as LF. `data/`, `tests/fixtures/` and `examples/` are `-text`, so hashes agree across platforms.
- **`tomd_version`.** In the synthetic set it is the workspace tomd version when the set was built. The version that produced the fixtures is not recorded anywhere.
- **Model calls.** Counted as 2 + criteria × sections × samples per proposal, which is the spec's formula. Tokens are not recorded, because paperweight's command line does not report usage.
- **Extra verbs.** Besides the four in the spec, the CLI has `choose`, `record`, `baseline` and `check-set`, which CI and set maintenance need.

## What in the spec turned out wrong or incomplete

- Runvil runs **Lua 5.5**, not 5.4. The prompt's comment "Lua 5.4 makes the loop variable const" describes 5.5 behaviour; 5.4 allows the assignment.
- **"Replay can evaluate the band-span rule"** holds only for `band_span` as it is written today, through `LABELS`. A change to the function itself is a code change replay does not model, so it needs a full run.
- **Tokens.** The spec says to print tokens when the gateway reports usage. paperweight's command line does not pass usage on, so only calls and wall time are recorded.
- **`tests.yml` runs on `push` to `main`, but the default branch is `master`.** Pushes to `master` never build the `paperweight-linux-x86_64` artifact; only pull request runs do. The full-run job therefore finds a binary for a pull request's head commit, but a dispatch on a `master` commit may find none.
- **The repository-wide `uv run pytest` that CLAUDE.md lists fails at collection on a clean checkout.** Eleven tomd test modules do `from conftest import make_block` and get pipeline's `conftest.py`. CI runs each package separately, and that way all tests pass. This was recorded before any work here and left alone.
- **The root `.gitignore` ignores every `data/` directory.** The spec's `packages/calibrate/data/` needs a negation, which was added the way assay's is.
- **`uv lock` with a current uv (0.13) rewrites `uv.lock`** (revision 3 to 5) and drops platform markers from torch's CUDA dependencies. The lock was regenerated with uv 0.9.5, so the diff adds only `calibrate` and `lupa`.

## Open questions for Vinnie

- [ ] Can the ten papers and the three reviewers' per-criterion grades be checked in, and can the reviewers be named or should they be initials? The loader, the schema and `check-set` are ready for them (see "Swapping in the golden set").
- [ ] Are the scripts and runs behind the numbers in the prompt's comments available? Their `diagnostics.md` files would replace the synthetic parity fixtures as milestone 1's evidence. The parser reads the format the current prompt prints; older runs from before the switch to section means would need checking.
- [ ] Which model and gateway setup produced those numbers? The harness needs that id as `CALIBRATE_MODEL`, and its baselines are per model.
- [ ] Would you accept the small Analyze-epilogue change in [calibration-harness-upstream.md](calibration-harness-upstream.md), which appends diagnostics only under `--args diagnostics`? A test applies it as written and shows that reports are byte for byte unchanged without the argument.
- [ ] Is there a monthly budget for full runs, or a local model behind the gateway? A full run of ten papers × three repeats is about 3,000 to 7,000 calls (the spec's table), and the shim's call count matches the spec's formula.
- [ ] Should this stay in wg21-paperflow as `packages/calibrate`, or become a Runvil prompt or Host? The shim already runs the prompt's own Lua outside Runvil. The scripted Host from the Attest CLI runner spec would let replay run through Runvil itself and retire both the shim and the Python copy of the arithmetic.
- [ ] New: the `tests.yml` `push` trigger names `main`, not `master`. Is that intended? The full-run job depends on that workflow's binary artifact.
- [ ] New: should the triage stub's rule match how the store is actually triaged? The shim calls a paper a proposal unless its id is not a P-number or its front matter says `intent: info`. P4020R0, a position paper, counts as a proposal under that rule.
