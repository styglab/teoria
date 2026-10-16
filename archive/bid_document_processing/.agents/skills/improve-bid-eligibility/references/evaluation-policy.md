# Evaluation policy

## Source-derived expectations

Newly sampled notices have no pre-existing ground truth. Codex must construct expected facts by reviewing the original parsed blocks and structured API restrictions independently from the extraction output. Every expected document fact needs an exact excerpt and source locator; structured API facts need the supplied record identifier. Never copy, paraphrase, or reverse-engineer expected facts from the current production output or fresh model output.

For discovery, complete and seal the source review before revealing the fresh output. For holdout, do not inspect the source or output during development; after regression passes, derive and seal source expectations before revealing that case's fresh extraction output. Mark genuinely ambiguous cases `adjudication_required` and exclude them from pass-rate denominators until resolved.

## Dataset partitions

- `discovery`: inspect freely to find failure modes and develop fixes.
- `regression`: frozen cases for all previously accepted behaviors and defects. Run on every change.
- `holdout`: sample before the iteration, leave both sources and extraction outputs untouched while developing, and evaluate once after regression passes. A holdout failure belongs to the next iteration.

Never promote the same artifact to both discovery and holdout within one iteration. Deduplicate by notice number/order, document checksum, and normalized-text similarity where available.

## Fresh extraction requirement

Run the current extraction stack and model anew for every extraction-ready discovery and holdout notice. Use `scripts/extract_sampled_cases.py` with write-free evaluation mode and retain its ephemeral manifest. Existing production outputs are diagnostic context only and never count as evaluation outputs.

The runner emits exact model inputs as `*.source.json` and fresh outputs as mode-000 pending files. `seal_source_review.py` validates cited Evidence against the source input and seals both files' hashes. `reveal_extractions.py` reveals an output only after the matching review seal verifies. Record non-ready and failed cases individually and continue the sample.

An end-to-end denominator contains only cases with a fresh output and independently source-derived expected facts. Report acquisition or parsing failures separately; do not silently replace them. Selector-only audits, synthetic fixtures, and regression tests may localize or prevent defects but cannot satisfy the fresh-extraction or holdout gate.

## Comparison units

Measure the pipeline in layers:

1. document availability;
2. parser text/table recall;
3. selector candidate recall;
4. fact recall and unsupported-fact precision;
5. type, holder scope, stage, failure effect, comparison mode, value, and date accuracy;
6. Evidence and proposition-span validity;
7. logic placement and compiled expression accuracy;
8. persistence, fingerprinting, and reselection behavior.

Report exact counts with denominators. Do not collapse `partial`, unsupported, or adjudication-required cases into ordinary failures.

## Default severity

- `critical`: unsupported requirement; missing mandatory bidder gate; inverted logic; wrong alternative branch that changes eligibility; fabricated Evidence.
- `major`: wrong type, scope, assessment stage, comparison mode, or material value that can change assessment behavior.
- `minor`: canonicalization, wording, redundant Evidence, or metadata defect that cannot change the eligibility result.

## Acceptance gate

Unless the user specifies stricter thresholds:

- zero critical regression failures;
- zero unsupported document-derived facts in regression and holdout;
- 100% valid Evidence and proposition spans for emitted document facts;
- no decrease in mandatory-gate recall, logic accuracy, or holder-scope accuracy;
- all repository tests and required validators pass.

Small holdouts do not prove population quality. Report confidence limits or plainly state sample limitations rather than claiming convergence.

If a gate fails, proceed to another iteration without waiting for an external dataset, provided a safe reproducible fix or another diagnostic sample is available. A holdout failure becomes discovery input for the next iteration and the next iteration receives a newly frozen holdout. Passing one small holdout does not erase unresolved critical discovery failures.

## Change discipline

Add the failing case first. Fix the earliest failing layer. Prefer invariant-based logic over phrase lists. If a phrase list is unavoidable, include positive, negative, and near-miss tests. Record parser, selector, schema, Skill, model, semantic-repair, expression-builder, and fixture versions whenever applicable.
