SYNTHETIC: everything in this directory comes from the Lua shim and the synthetic set, except `what-the-checks-found.html` (see below); no number here is a finding about paperweight's accuracy.

# Examples

`synthetic-comment.md` is the acceptance run from the spec, made end to end on
synthetic data: a pull request that changes `INTER_RULE` from `top2` to `max`
gets a replay comment with no model calls. Its numbers come from simulated
reviewers and a simulated grader, so they show the harness working, not how
paperweight behaves.

`candidate-inter-rule-max.md` is the candidate prompt: paperweight.md with
`INTER_RULE = "max"` and nothing else changed, made by
`calibrate.aggregate.patch_constants`. The examples were made against the
prompt with sha256 `8b903808` (first eight hex digits; CRLF read as LF).

To make them again, from the repository root:

```bash
uv run calibrate full --set packages/calibrate/data/synthetic --repeats 3 --jobs 4 --profile calibrated --seed 1
uv run python -c "from pathlib import Path; from calibrate import aggregate; p = Path('crates/paperweight/paperweight.md').read_bytes().decode().replace('\r\n', '\n'); Path('packages/calibrate/examples/candidate-inter-rule-max.md').write_bytes(aggregate.patch_constants(p, INTER_RULE='max').encode())"
uv run calibrate choose --prompt packages/calibrate/examples/candidate-inter-rule-max.md --from calibration-runs/<baseline>
uv run calibrate replay --prompt packages/calibrate/examples/candidate-inter-rule-max.md --from calibration-runs/<baseline>
uv run calibrate compare calibration-runs/<replay> calibration-runs/<baseline> --set packages/calibrate/data/synthetic --out packages/calibrate/examples/synthetic-comment.md
```

`full` prints the baseline folder and `replay` the replay folder. Everything is
seeded, so the same prompt gives the same comment.

The direction of the bias is fixed by the arithmetic, not by the simulation:
for every criterion the max over sections is at least the mean of the two best
sections, so no total can fall when `top2` becomes `max`. How far it rises
depends on the simulated grader, and says nothing about the model.

## The explainer pages

All three are the sources of pages published as Claude artifacts, so they carry no
`<html>` or `<head>` of their own; open them in a browser as they are.

- `how-calibration-works.html` is the plain-language overview: one animated
  picture of the loop, from a prompt change to the report on the pull request,
  for readers who want the idea and not the numbers.
- `calibration-lab.html` is the hands-on version. It embeds the votes recorded
  in the synthetic baseline run (12 papers, 3 repeats) and recomputes the
  epilogue's arithmetic in the browser as you change `INTER_RULE`, `STRONG`,
  `CORROBORATION`, `ACCUM_FULL` and the band edges. On load it checks itself
  against every total and verdict line the Lua printed. Every number on it is
  synthetic, and the page says so.
- `what-the-checks-found.html` is part 2 of the overview, and the one page here
  that is not synthetic. Its first three steps are real `gpt-6-luna` output
  from the full run of 2026-10-27, shown without the synthetic grades, so they
  describe how paperweight behaved on that model, not how accurate it is. Its
  next three steps are PROXY: the ICLR 2025 reviewer study in
  `../studies/iclr-2025-reviewers.md`. Each step is labelled with which it is.
