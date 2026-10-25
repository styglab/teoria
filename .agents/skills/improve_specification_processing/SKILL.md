---
name: improve-specification-processing
description: Run bounded source-backed improvement cycles for Teoria procurement specification extraction using its frozen evaluation CLI. Diagnose hierarchy, relation, requirement and ownership failures, repair the owning code, compare baseline and candidate, and delete bulky cycle artifacts after reporting.
---

# Improve Specification Processing

Read the [ownership rules](../../../docs/architecture/repository-structure.md) and
[evaluation/execution contract](../../../docs/procurement_specification_processing/evaluation.md).
Code and tests belong to Pipelines' `public_procurement/specification_processing/`.
Use its evaluation entrypoint rather than creating a second sampler, scorer or cleanup script.
The evaluation Flow runs the actual shared extraction Tasks 00–05; it does not measure standardization,
operational DB completion, or deployment. Source-only extraction must remain independent of server catalogs.

## One bounded cycle

Default to one cycle and computer-server documents with classification `4321150102` confirmed by collected
notice/item metadata. Use locally available originals; acquiring another corpus requires that task scope.
A requested repeat run defaults to at most three cycles, stopping on budget exhaustion, two consecutive
cycles without improvement, executor failure, missing prerequisites, or contradictory source evidence.
Never restore automatic notice attachment collection or retired experiments.

1. Prepare a manifest using the maintained schema in the execution contract. Include source and metadata
   hashes, classification/notice JSON pointers, model, parser configuration, and any existing source-derived
   entity/relation/requirement cases. Unknown past exposure stays unknown. Audit historical manifests and
   feed their notice IDs/hashes into exclusions; never reset history to make documents appear new.
2. Run `prepare`, then `baseline` before editing code. Code freezes the grouped random sample, seed,
   cases and evaluator and records notice/hash/template use history. Default sample size is 10, targeting
   five development and five validation documents. Whole groups may change those counts. Fixed regression
   documents are additional; they do not count as fresh samples. If too few independent groups exist, report it.
3. Inspect development originals and baseline results. Find one source-backed defect, classify it as parser
   loss, IE omission/relation/ownership, or downstream standardization. Do not inspect validation outputs
   to choose the fix. A parser defect needs evidence and separate parser repair scope. Fix the responsible
   module and add a minimal source-backed regression test; do not hardcode document IDs, hashes or wording.
4. Run `candidate`, then `finish`. Candidate uses the same inputs, settings and frozen cases; finish compares
   development, validation and regression, executes Pipeline tests, reports accepted/rejected/inconclusive,
   and removes the workspace in a finalization path. Keep accepted repairs only within the user's authorized
   scope. Revert only your unsuccessful repair, preserving unrelated workspace edits. Do not publish/deploy.
5. Report the observed defect, change, before/after case counts, actual tests, limitations, and removed/retained
   bytes. Do not describe synthetic/mocked tests as real-model evaluation or partial labels as full recall.

```bash
uv run --locked --project backend teoria-pipelines specification evaluate prepare --manifest /data/evaluation.json
uv run --locked --project backend teoria-pipelines specification evaluate baseline --cycle-id server_cycle_01
# Inspect development results and repair the responsible code here.
uv run --locked --project backend teoria-pipelines specification evaluate candidate --cycle-id server_cycle_01
uv run --locked --project backend teoria-pipelines specification evaluate finish --cycle-id server_cycle_01
```

Use `evaluate --state-dir PATH` before the step name when a separate summary location is needed.
Keep the temporary workspace only while actively comparing/repairing. Never create archives or code snapshots.
Use `abort --cycle-id ID` on abandonment or failed preflight. Worker failures/cancellation clean automatically;
a hard process kill may leave pending cleanup. Resolve it with `abort` before preparing another cycle.
Do not delete shared DB rows, operational S3 artifacts, input originals or baseline standards as cleanup.

## What counts as evidence

The CLI checks source literals, references, fixed relation direction, requirement subjects/owner/scope and
provided cases. It preserves failed documents in denominators and does not equate output counts with quality.
AI-authored cases are silver labels; label uncertainty is not pipeline failure. Correcting an oracle is a
separate change, never an improvement score. Missing cases, unpinned model, changed parser version or
unchanged processor cannot establish a quality improvement. The matcher is intentionally conservative;
inspect fair failures rather than changing scoring rules or labels during a cycle.

Use contract v2 annotations: distinguish entity existence from a particular mention, annotate owners for
ambiguous names, and freeze only source-confirmed aliases. Unannotated qualifiers are not an assertion of
absence; use required subsets normally, explicit exact lists for absence/equality, and forbidden qualifiers
where needed. Do not weaken subject/value/unit/operator/ownership or source-grounding checks.
If the oracle conflicts with the source, abort that cycle first. Correct the grader/labels separately and use
`purpose: grader_calibration` with `replay_of` in a new manifest, then `prepare → baseline → finish`.
This replay preserves source identities, original split membership and exposure history; it permits a known
subset and records `baseline_recorded`, never an extraction improvement or a fresh validation claim.
See the execution contract for the annotation and replay fields.

Final outputs are compact `.artifacts/specification_improvement/state.json` and `index.md`, updated across
cycles. Preserve input originals and minimal fixed regression cases. Bulk parsed output, model responses,
logs and extraction results are temporary and are deleted by finish/abort. This lifecycle belongs to evaluation;
ordinary pipeline artifact retention is unchanged. Human review is not a per-cycle execution gate, and
no AI score or accepted repair publishes Ontology or authoritative metadata.
