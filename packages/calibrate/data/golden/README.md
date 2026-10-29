# Golden calibration set

The real set the harness scores paperweight against: the papers the prompt's
aggregation rules were tuned on, and the human reviewers' grades. It is empty
until the team checks the data in. Until then the harness runs on
`../synthetic/`, which has this layout and is marked SYNTHETIC on every file.

Nothing synthetic may ever be placed here. The loader refuses a set under a
`golden` directory whose files say SYNTHETIC, and refuses a set whose files
disagree about it.

## Files

| File | Holds |
| --- | --- |
| `README.md` | This file, plus where the papers and grades came from, who the reviewers are (names or initials), and the labeling rules they followed |
| `papers.jsonl` | One line per paper: `paper` (for example `P3643R3`), `markdown_sha256`, `tomd_version`, `split` (`calibration` or `holdout`) |
| `papers/<paper>.md` | The exact markdown each reviewer graded against, byte for byte |
| `grades.csv` | A header `paper,reviewer,criterion,grade`, then one row per paper, reviewer and criterion, with `grade` 0, 1 or 2 |

`papers.jsonl` lines carry no `synthetic` field, or `"synthetic": false`.
`grades.csv` starts with its header line. Line endings in this directory are
kept as committed (`-text` in `packages/calibrate/.gitattributes`), so a hash
taken on any platform matches.

## Rules the loader enforces

- Every `markdown_sha256` matches its `papers/<paper>.md`.
- Every grade is 0, 1 or 2, and every paper, reviewer and criterion has
  exactly one.
- Criteria use the prompt's internal `short` names, and the set of graded
  criteria equals the prompt's `CRITERIA` table in both directions:
  `motivation`, `audience`, `prior_art`, `vehicle`, `coordination`,
  `insufficiency`, `implementation` as of this writing.

The ten papers the prompt was tuned on are `calibration`. Papers graded later
go in as `holdout` and are reported separately, because every number on the
ten is in-sample.

## Validate

```bash
uv run calibrate check-set
```

Exits non-zero on any error above. `--set` points it at another directory.

## To do when the data arrives

See `docs/plans/calibration-harness-status.md`, "Swapping in the golden set".
