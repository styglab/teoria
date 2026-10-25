---
name: align-metadata-semantics
description: Propose Semantic Bindings between OpenMetadata assets or glossary terms and existing published Teoria Ontology concepts. Use for business meaning alignment and binding gaps; never create new Ontology concepts.
---

# 업무 의미 연결

Require the OpenMetadata table FQN and optional columns. Read `AGENTS.md`,
`docs/architecture/repository-structure.md`, and the
[evidence policy](../enrich-metadata-asset/references/evidence_policy.md).

Read the current asset using
`../enrich-metadata-asset/scripts/fetch_context.py` (resolve from this skill).
Identify existing Glossary terms, approved Bindings and Published Ontology
Stable Concept IDs using the Admin API and relevant repository evidence.
Authoring YAML alone does not prove that a concept is published.

Compare business definition, unit, identity and time semantics against source
contracts and cited documents. A similar name is a candidate, not proof.
Prefer `Physical Asset -> Glossary Term -> Ontology`; direct asset bindings are
allowed and do not outrank the glossary path. Do not duplicate an approved
binding. Return `unbound`, alternatives or `needs_evidence` when the match is
missing or ambiguous. Do not invent a concept to fill the gap.

Create one independently reviewable `binding` suggestion per verified match.
Use the actual contract in `backend/src/teoria/features/metadata_management/intelligence/suggestions/contracts.py` and the
[bundle schema](../enrich-metadata-asset/references/proposal_bundle.schema.json);
do not invent new API fields. Include the published stable concept key, current
OpenMetadata version, evidence, confidence and material alternatives.
Use medium risk unless stronger policy requires high risk. Name-only or
conflicting matches remain below 0.7 and carry a warning.

Validate from the repository root with `uv run --locked --project backend python .agents/skills/enrich-metadata-asset/scripts/submit_proposals.py <bundle>`.
Submit with `--submit` only when requested by the user. Report pending suggestion
IDs. Approval creates a Binding Draft; a separate Binding review activates it.
Never call review endpoints, publish Ontology, or write OpenMetadata.
