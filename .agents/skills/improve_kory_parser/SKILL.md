---
name: improve-kory-parser
description: Evaluate and improve the archived Kory Parser library using source-backed document cases, regression tests, and bounded repair cycles. Use for parser quality and performance work, not business information extraction or active Teoria service integration.
---

# Improve Kory Parser

Kory Parser is an independent document-structure library in `archive/kory_parser/`.
Keep changes there; do not connect it to Platform, Pipelines, Registry or deployments.
In an isolated repair candidate, the working directory itself is the package root.

Read `docs/evaluation_loop.md` in the package for the manifest contract and commands.
For a real-document improvement cycle also read `docs/public_procurement_cycle.md`.
Do not stop after the synthetic seed passes: sample actual public bid attachments
from Teoria's collected notices, run the parser and kordoc, then identify deficiencies.
Use `evaluations.public_procurement.export_notices` for a read-only attachment frame
through the Pipeline DB boundary when the MCP projection does not expose attachment URLs.
Keep sampling and downloads in this archive's local artifacts; do not restore a
production attachment ingestion or parsing service.
Omit `--seed` in ordinary new exploration runs: export and sampling generate fresh
seeds and record them. Preserve the shared `.artifacts/corpus_history/state.json`.
Register previous corpora before sampling; do not reset the history to obtain more
apparently fresh cases. Exclude prior notices before download and prior bytes by
SHA-256 even at a different URL. Keep the frozen regression manifest unchanged.
Use the separate development and validation manifests; validation must use unseen
families. If fresh data is insufficient, broaden the notice frame rather than
refilling with used documents. Replay stored manifests to reproduce an evaluation.
Repository-root invocation example:

```bash
cd archive/kory_parser
uv run --locked python -m evaluations --output .artifacts/evaluation_before
```

Use sampled development failures or supplied cases to select one underlying defect. Inspect the
source document or authored XML and its evidence before changing parser behavior.
Add a focused regression test and fix the responsible parser module. Avoid branches
based on case IDs, file hashes, fixture wording or document-specific coordinates.

Preserve existing tests, manifests, expected results, thresholds, evaluation code,
dependencies and parsing options during a repair cycle. Add regression tests rather
than weakening existing tests. If source evidence shows the oracle is wrong, report
it as a separate corpus correction; do not count a label change as parser progress.

Run the original test suite, new regression tests and the same development evaluation.
The outer evaluator runs validation cases and compares every metric; improvements
must not hide regressions in other documents. Do not inspect validation cases to
choose a fix. Public seed validation is a smoke check, not a secret holdout.

In a normal session, default to one repair cycle. For a requested repeat run use the
bounded `evaluations.improve` entrypoint; inside its candidate never launch another
Codex process or improvement loop. Stop on the configured budget, repeated no progress,
missing input, contradictory oracle evidence, or executor failure. Preserve partial
results and state the reason. Do not substitute fabricated results for unavailable
real-document evaluations.

For sampled documents freeze the baseline and edit a separate candidate. Run
`evaluations.benchmark` on identical bytes/options for baseline, candidate and pinned
kordoc; run `evaluations.public_procurement.probes` against source-derived or visually
reviewed original evidence. Reference agreement alone is not source accuracy.
Partial probes do not satisfy the full-output manifest contract of `evaluations.improve`.
Use `evaluations.public_procurement.gate` for the final decision: quality improvement,
no source-check regressions, unchanged non-target outputs, passing tests, and bounded
timing regression. Confirm timing warnings with five repetitions. Preserve both runs.
Replay the fixed pool using `evaluations.public_procurement.regression` every cycle
and pass its report plus the sampling cycle manifest to the gate. A missing,
incomplete, changed-pool or changed-source replay must prevent promotion.
If the user authorized applying improvements, use `--apply` only after that gate accepts;
this does not require another approval. Rejected or inconclusive candidates stay as evidence.
Record unresolved source-backed review candidates for the next cycle and distinguish
confirmed defects from suspicious signals. Retire inspected validation cases into the
regression pool; use fresh notice/template groups for future blind validation claims.

Report the defect, change, regression coverage, metric changes and remaining limits.
Finish a completed cycle with the report command's default cleanup. Keep fixed
regression originals, labelled/problem cases, usage hashes/manifests, comparison
reports and frozen sources; remove unneeded successful samples and regenerable
intermediate copies. Do not clean unfinished validation sets or an unapplied
accepted candidate. Preserve use history even when sample bytes are removed.
Use `--keep-intermediates` only when the task needs the full debugging artifacts.
Keep source documents and executor logs in ignored local artifacts. Never publish,
commit, apply a saved candidate to another checkout, or change the oracle as an implied
part of evaluation. Those actions require a task that actually includes them.
