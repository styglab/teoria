---
name: enrich-metadata-asset
description: Propose evidence-backed table and column descriptions and glossary terms for OpenMetadata assets. Use for missing or inaccurate metadata and terminology enrichment; use align-metadata-semantics for existing Ontology bindings and assess-data-disclosure for legal disclosure assessment.
---

# 메타데이터 정비

Create reviewable metadata suggestions without turning model output into authoritative metadata.

## Inputs

Require an OpenMetadata table FQN and, when applicable, one or more column names. Accept source documents or repository paths as additional evidence. Ask for the missing table FQN rather than guessing it.

## Workflow

1. From the repository root, read `AGENTS.md`, `docs/architecture/repository-structure.md`, and `references/evidence_policy.md` in this skill.
2. Fetch the current OpenMetadata table context through Teoria Admin API:

   ```bash
   python3 .agents/skills/enrich-metadata-asset/scripts/fetch_context.py \
     --table-fqn '<service.database.schema.table>' \
     --output /tmp/teoria_metadata_context.json
   ```

   Set `TEORIA_ADMIN_BASE_URL` or `--admin-base-url` for the reachable Admin API. The default Compose entrypoint is `http://localhost:8081/admin-api`; a container on its network can use `http://admin-api:8001`. Bearer reads use `TEORIA_ADMIN_API_TOKEN`. This step is read-only. If OpenMetadata is unavailable, report that limitation and continue only when repository or user-provided evidence is sufficient.
3. Inspect only relevant evidence:
   - the selected table and column metadata;
   - existing ontology concepts and semantic bindings under `platform/`;
   - active Source Registry contracts and mappings when they establish field meaning;
   - user-provided or repository source documents;
   - bounded, read-only data samples only when the user authorized them and the registered Database Source supplies the query path.
4. Separate observations from inference. Do not infer authoritative meaning from a similar name alone. Propose descriptions, existing Glossary assignments, or new Glossary terms supported by governed definitions. Route Ontology bindings to `$align-metadata-semantics` and disclosure diagnosis to `$assess-data-disclosure`.
5. Produce a bundle conforming to `references/proposal_bundle.schema.json`, generated from `platform/src/teoria/intelligence/suggestions/contracts.py`. Use one suggestion per independently reviewable change. Record the OpenMetadata version in evidence provenance and add content hashes for local documents when available.
6. Validate locally without submitting:

   ```bash
   uv run --locked --package teoria-platform python \
     .agents/skills/enrich-metadata-asset/scripts/submit_proposals.py proposal_bundle.json
   ```

7. Show the user the proposed changes, evidence, confidence, warnings, and unsupported gaps. Submit only when the user asked to place proposals in the Review Queue:

   ```bash
   uv run --locked --package teoria-platform python \
     .agents/skills/enrich-metadata-asset/scripts/submit_proposals.py \
     proposal_bundle.json --submit
   ```

   The script reads `TEORIA_ADMIN_API_TOKEN` when bearer authentication is enabled. Never print the token.
8. Report created suggestion IDs. Stop there. Never call review endpoints, approve a Binding, publish an Ontology revision, or write directly to OpenMetadata.

## Proposal rules

- Use `model_provider: openai` and the actual model name when an OpenAI model produced the proposal. Never claim a model or version that was not used.
- Use `risk_level: medium` for semantic bindings and glossary assignments unless stronger policy requires `high`.
- Set confidence from evidence strength, not prose fluency. Missing source documentation, conflicting evidence, or name-only matches must remain below `0.7` and carry a warning.
- A binding proposal must identify a published stable Ontology Concept ID and retain alternatives when ambiguity is material.
- An API-field claim is eligible only when an active Source Registry operation verifies the original field.
- Column-description suggestions must include `table_id`, `column_name`, `column_fqn`, `source_version`, and `source_description` so approval can distinguish a sibling column update from a change to the reviewed target.
- New Ontology authoring is deferred. Report missing business meaning as `needs_evidence` or an unbound gap; do not generate `ontology_change`, `test_suite`, or `quality_test` proposals in this workflow.

## Success criteria

- Every suggestion validates against the bundle contract.
- Every material claim has traceable evidence or is explicitly marked as inference.
- No OpenMetadata entity body is copied into Teoria persistence.
- The Review Queue contains only pending suggestions, with no automatic approval or application.
