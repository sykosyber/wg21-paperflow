# Proposal: let paperweight append its diagnostics when asked

Oct 26, 2026 · for the paperweight maintainers · optional, not applied

The calibration harness (`packages/calibrate`) needs the per-section votes that
paperweight already computes and keeps in its store as `diagnostics.md`. This
proposes a small change to the Analyze epilogue of
`crates/paperweight/paperweight.md`: append that file to the report when, and
only when, the run is started with `--args diagnostics`. Deployed reports do not
change. It has not been applied, and nothing in `crates/` was modified.

## Why

The harness replays aggregation changes on recorded votes and checks parity
between its Python copy of the epilogue and the numbers the Lua prints. Both
need `diagnostics.md`, which a run leaves in its store but never writes out.
paperweight's command line writes only the declared output, `report.md`.

Today the harness works around this. For a full run it passes paperweight a
copy of the prompt, through `--prompt`, in which the commented appendix in the
Analyze epilogue is restored and added to the report write
(`calibrate.run.diagnostics_patch`). That works, but the patch is keyed to the
exact text of the comment, so any edit to those lines breaks it (it refuses to
apply rather than guess), and every full run executes a prompt that is not
byte for byte the one under review.

## The change

````diff
--- a/crates/paperweight/paperweight.md
+++ b/crates/paperweight/paperweight.md
@@ -1181,17 +1181,21 @@ if not weight_line:find("%S") then
     weight_line = "Weight: n/a"
 end
 
--- The diagnostics are still built in full and left in the store as
--- diagnostics.md: per-section sample votes, section means, every candidate
--- quote with its agreement count, the totals under all four inter-section
--- rules, grader unanimity, the single-sample simulation and the split triples.
--- They are simply not appended to the report. To get them out of a run, read
--- diagnostics.md from the store, or restore the appendix below.
---
---   local diag = read_or_empty("diagnostics.md")
---   local appendix = diag:find("%S")
---       and ("\n\n<!-- paperweight-diagnostics\n" .. diag .. "\n-->\n") or ""
+-- The diagnostics are built in full and left in the store as diagnostics.md:
+-- per-section sample votes, section means, every candidate quote with its
+-- agreement count, the totals under all four inter-section rules, grader
+-- unanimity, the single-sample simulation and the split triples. They are
+-- appended to the report only when the run's arguments ask for them
+-- (`--args diagnostics`), so deployed reports are unchanged. The calibration
+-- harness (packages/calibrate) asks for them to read the votes back.
+
+local appendix = ""
+if (args or ""):find("diagnostics", 1, true) then
+    local diag = read_or_empty("diagnostics.md")
+    appendix = diag:find("%S")
+        and ("\n\n<!-- paperweight-diagnostics\n" .. diag .. "\n-->\n") or ""
+end
 
-store.write("report.md", weight_line .. "\n\n" .. body .. "\n")
+store.write("report.md", weight_line .. "\n\n" .. body .. "\n" .. appendix)
 return "Done."
 ```
````

`args` is the Engine global that holds `--args` verbatim (paperweight's
prompt declares no `args:` contract, so it is plain text). The search is a
plain substring match, so `--args diagnostics` and an argument string that
merely contains the word both turn it on; nothing else reads `args` today.

## What it does and does not change

- Without `--args diagnostics`, `report.md` is byte for byte what it is now:
  `appendix` is the empty string. Nothing on wg21.org changes.
- With it, the report gains the diagnostics as an HTML comment after the prose,
  in the format the commented code already describes. The verdict line, the
  prose and every grade are unchanged; the diagnostics were computed anyway.
- No model call, no new store file, no change to the Assess section, so replay
  remains possible across this change (it touches the Analyze epilogue only,
  which the harness's mode chooser treats as needing a full run, as it should
  for any Analyze change).

`packages/calibrate/tests/test_upstream_proposal.py` applies the diff above, as
written in this file, to the current prompt and runs it through the Lua shim
both ways, so this document cannot drift from what it claims.

## What the harness does once it lands

`calibrate.run.BinaryBackend` stops patching the prompt and passes
`--args diagnostics` with the prompt as given, and `meta.json` records
`"diagnostics_from": "report appendix, via --args diagnostics"`. The
`diagnostics_patch` function and its tests are removed in the same change.
