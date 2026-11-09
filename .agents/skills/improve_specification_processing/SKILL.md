---
name: improve-specification-processing
description: "Improve Teoria specification extraction through bounded real-pipeline evaluation cycles: discover local originals, freeze source-backed cases, repair and compare, verify integration separately, and clean final and intermediate evaluation artifacts on every exit."
---

# Improve Specification Processing

Read the [ownership rules](../../../docs/architecture/repository-structure.md) and
[evaluation/execution contract](../../../docs/domains/goods/specifications/evaluation.md).
Code belongs to `backend/src/teoria/domains/goods/`; tests follow the same feature under `backend/tests/`.
Use its evaluation entrypoint rather than creating a second sampler, scorer or cleanup script.
The evaluation Flow runs the actual shared extraction Tasks 00–05; it does not measure standardization,
operational DB completion, or deployment. Source-only extraction must remain independent of server catalogs.

## Select sources and bound the work

For an improvement request, run at most three cycles. Stop after two consecutive cycles without a
measured improvement, budget exhaustion, an executor failure, missing prerequisites, or contradictory
source evidence. Count accepted improvements separately from inconclusive fixed-source observations.
This skill is invoked work, not a background scheduler.

The agent finds additional originals and authors the cases; do not send routine source comparison back
to the user. Start with `evaluate status`, then `evaluate discover --root .artifacts/sample` and other
available local document locations relevant to the request. Discovery inventories files and exposure only;
it does not infer a goods classification, recognize a template, or create an oracle. Review historical
manifests/use hashes and source layouts before assigning template_family and claiming fresh inputs.
The known ten samples are regression material; they are not fresh validation documents. Select different
file formats, table structures and goods where available. Do not treat duplicate bytes or another copy of
one template as an independent document. Report a lack of eligible sources instead of relabelling old inputs.
Never reconnect retired notice-attachment ingestion. Use public downloads only when within the user's
source-acquisition scope; record the original location/hash and retain the downloaded input.

Choose `unclassified_random` with classification_code=null for new mixed-goods documents without notice
metadata; it groups related hashes/templates into development/validation and excludes known regressions.
Use `classified_random` only with verified notice/classification metadata, and `fixed_sources` for known
replays without independent acceptance. Do not assign the server classification from the filename.

## One bounded cycle

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
   scope. Revert only your unsuccessful repair, preserving unrelated workspace edits. Do not publish Ontology.
   Deploy only when the session authorizes deployment and the separate integration checks pass.
5. Before promoting a surviving repair, perform the integration checks below in an isolated environment.
   `finish` has already removed the extraction workspace; use an independently owned integration environment.
   Use `abort` if abandoned and confirm cleanup via `status`. Retain a compact
   integration summary in the maintained verification report; do not retain full evaluation outputs.
6. Report the observed defect, change, before/after case counts, actual tests, limitations, and removed/retained
   bytes. Do not describe synthetic/mocked tests as real-model evaluation or partial labels as full recall.

```bash
uv run --locked --project backend teoria-pipelines specification evaluate status
uv run --locked --project backend teoria-pipelines specification evaluate discover --root .artifacts/sample
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

## Separate full-pipeline verification

The extraction CLI cannot certify downstream storage or the UI. Use the existing
`teoria-pipelines specification run --manifest ...` entrypoint for actual Task 00–09 verification;
do not substitute a second extraction implementation or mock HTTP/DB success.
Use a dedicated test Data DB, a cycle-owned artifact prefix/directory, an isolated Prefect environment,
and pinned standard/dictionary snapshots. Disable automatic dictionary/meaning approvals and stage
checkpoint reuse. Keep source hashes/model/parser settings aligned with the evaluated candidate.
Do not point the integration run at production DB/artifact configuration or submit authoring changes.
If an isolated environment or snapshots are unavailable, record integration as not_run with the reason;
extraction acceptance alone does not mean deployment readiness.

Check final run/document states (including retained partials), artifact checksums, per-document catalog/result
retrieval, and the frontend hierarchy/attribute/source-evidence display. Verify a real staging web instance
when available; frontend fixture tests alone do not establish a deployed web check. Record the checked
run IDs, checks, limitations and a compact verdict, without credentials or document bodies.
In a finalization path remove only the integration run's registered rows and owned objects, after confirming
that no current result/standard/original references them. Prefer a disposable environment that can be
removed as a unit. Include cleanup in the result even when the integration check fails. Never use broad
DB deletion or S3 prefix pruning against an existing deployment. This integration cleanup is separate from
the extraction CLI's automatic local workspace cleanup. Failed integration stops deployment.

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
logs, final extraction/normalization outputs, diagnostic archives, browser captures and temporary copies
are evaluation artifacts: delete them after capturing the compact report, including on rejection, timeout,
exception and cancellation. The CLI frozen manifest lives inside its owned workspace. Keep agent-generated
input manifests and auxiliary reports in a task-owned temporary directory, and remove that directory in the
agent finalization path as well. A caller-supplied manifest and original documents are not disposable copies.
The CLI removes its entire owned workspace on finish/abort; status must show cleanup=complete.
If deletion fails, keep cleanup=pending and retry `abort`; never claim cleanup succeeded or start another
cycle while it is pending. A cleanup retry must preserve an already finished comparison verdict. This lifecycle belongs to evaluation;
ordinary pipeline artifact retention is unchanged. Human review is not a per-cycle execution gate, and
no AI score or accepted repair publishes Ontology or authoritative metadata.
