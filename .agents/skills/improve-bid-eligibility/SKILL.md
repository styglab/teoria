---
name: improve-bid-eligibility
description: Repeatedly improve Korean public-procurement bid eligibility extraction by stratified resampling, fresh write-free model extraction of real notices, independent Codex review against original source evidence, error triage, regression capture, layer-specific fixes, and untouched holdout evaluation. Use when Codex is asked to audit, resample, validate, debug, tune, or iteratively improve Teoria bid-document parsing, candidate selection, eligibility extraction, semantic repair, expression building, or extraction quality metrics.
---

# Improve bid eligibility

Read `references/evaluation-policy.md`, `references/error-taxonomy.yaml`, and
`references/sampling-strata.yaml` before changing code. Validate evaluation cases against
`references/evaluation-case.schema.json`.

## Workflow

1. Read `docs/architecture/repository-structure.md` and inspect the current worktree. Preserve unrelated changes.
2. Define the evaluation run before sampling: population window, random seed, discovery count, frozen regression set, untouched holdout count, and acceptance thresholds. Never choose holdout cases after seeing their outputs.
3. Use `scripts/sample_cases.py` or an equivalent read-only query to sample across the strata in `references/sampling-strata.yaml`. Do not copy credentials, personal data, full private responses, or unnecessary document content into fixtures or logs.
4. Run every extraction-ready discovery notice through `scripts/extract_sampled_cases.py`. This must call the current model and the production parser, selector, semantic repair, schema validation, and expression compiler with `persist=False`. Never substitute existing production extraction rows, selector-only inspection, or synthetic outputs for this step.
5. Build the expected result yourself from the emitted `*.source.json`, which is the exact selected parsed-block and structured-restriction input sent to the model. There is no pre-existing ground-truth dataset for new samples. Read every relevant source passage and record exact Evidence for each source-derived expected fact without opening the mode-000 pending extraction. Seal each review with `scripts/seal_source_review.py`; it rejects Evidence absent from the source input.
6. Reveal outputs with `scripts/reveal_extractions.py` only after every corresponding source review is sealed. Compare with `scripts/compare_extractions.py`, which requires the seal and revealed manifest and checks normalized facts, Evidence, proposition spans, proofs, unresolved candidates, expression, and output-schema integrity. Classify the first failing layer with `references/error-taxonomy.yaml`; never infer expected facts from either production or fresh extraction output.
7. Reproduce every suspected defect from raw parsed blocks, structured restrictions, exact model input, fresh extraction output, and version metadata. Fix the earliest layer that lost or corrupted the required information. Do not compensate for parser or selector defects with prompt exceptions.
8. Add a minimal deterministic failing test or evaluation case before changing behavior. Use `scripts/export_case.py` to create a case skeleton and record exact evidence, expected facts, error class, severity, and provenance.
9. Implement the narrowest general rule supported by at least one reproduced case and a clear invariant. Do not add notice-number, organization, or document-specific patches.
10. Run the focused failing test, all related tests, then `uv run --locked --package teoria-pipelines pytest pipelines/tests`. Run repository-required validation for every project changed.
11. Evaluate the frozen regression set. Compare normalized fact outputs with `scripts/compare_extractions.py`; validate cases with `scripts/validate_case.py`. A fix is not complete if any prior critical case regresses.
12. Evaluate the untouched holdout exactly once after regression passes. For each holdout case, derive and seal expected facts from its source input before revealing its fresh extraction output. Do not edit against holdout failures in the same reported iteration; move diagnosed failures into the next discovery/regression cycle and draw a new holdout.
13. Summarize metrics with `scripts/summarize_evaluation.py`. Report sample composition, fresh-extraction completion rate, acquisition/parsing/extraction failures, errors by earliest layer and severity, before/after metrics, regressions, holdout results, changed files, remaining risks, and whether thresholds passed.

Run fresh extraction with partition-specific sample manifests and an untracked temporary directory:

```bash
uv run --locked --package teoria-pipelines python \
  .agents/skills/improve-bid-eligibility/scripts/extract_sampled_cases.py \
  --sample /tmp/discovery-sample.json --partition discovery \
  --output-dir /tmp/eligibility-evaluation/discovery
```

Run the holdout command only after the fix and frozen regression set pass. Confirm the output
manifest has `persist: false` before comparison. For each completed case, write the source review,
then run:

```bash
uv run python .agents/skills/improve-bid-eligibility/scripts/seal_source_review.py \
  --case /tmp/reviews/NOTICE_ORDER.json \
  --source-input /tmp/eligibility-evaluation/discovery/NOTICE_ORDER.source.json \
  --seal /tmp/reviews/NOTICE_ORDER.seal.json
uv run python .agents/skills/improve-bid-eligibility/scripts/reveal_extractions.py \
  --manifest /tmp/eligibility-evaluation/discovery/manifest.json \
  --reviews-dir /tmp/reviews
```

## Boundaries

- Use `$extract-bid-eligibility` only to perform a single extraction or revise extraction semantics. This skill owns evaluation and improvement orchestration.
- Separate retrieval recall from semantic extraction quality. A model cannot extract text it never received.
- Require exact Evidence for every document-derived expected fact. Count unsupported generated requirements as critical false positives.
- Preserve unfamiliar but explicit bidder gates as `custom`; do not improve headline precision by discarding hard cases.
- Do not weaken schema, citation, proposition-span, or expression validation merely to make samples pass.
- Do not deploy, mutate production extraction rows, bulk re-extract, or publish a Skill update unless the user requested that operational action. Sampling and inspection are read-only by default.
- `persist=False` is mandatory for discovery and holdout extraction. Verify the evaluation manifest says `persist: false`; do not use the production extraction task or flow as an evaluation shortcut.
- Treat `not_extraction_ready` and `extraction_failed` manifest entries as layer failures with their own denominators; never abort or silently replace the rest of the sample.
- Do not change file permissions or inspect `*.pending.json` before `reveal_extractions.py` succeeds.
- If fresh extraction or independent source comparison cannot run, report the evaluation as blocked or incomplete. Never describe parser/selector inspection, an existing production row, or a deterministic fixture alone as end-to-end extraction validation.
- Stop and report a source-meaning ambiguity when reasonable reviewers could disagree about eligibility meaning; record it as `adjudication_required` rather than forcing an expected answer.

## Evaluation artifacts

Keep durable, sanitized regression cases under `pipelines/tests/fixtures/` when they can run offline. Keep ephemeral discovery and holdout artifacts outside tracked paths unless the user requests publication. Each durable case must include the versions and provenance required by the case schema.

Use stable case IDs and never overwrite an accepted source-derived regression expectation to hide a regression. Amend it only with a documented source reinterpretation reason.
