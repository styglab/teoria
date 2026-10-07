---
name: analyze-metadata-asset
description: Analyze an OpenMetadata table or column against Teoria Business Ontology, Semantic Bindings, Source Registry, and cited source documents; produce evidence-backed description, glossary-term-assignment, or ontology-binding suggestions and optionally submit them to the Teoria Review Queue. Use for development-time metadata enrichment, missing column meaning, glossary or ontology mapping proposals, and metadata quality triage. Never use it to approve or directly apply suggestions.
---

# Analyze Metadata Asset

Create reviewable metadata suggestions without turning model output into authoritative metadata.

## Inputs

Require an OpenMetadata table FQN and, when applicable, one or more column names. Accept source documents or repository paths as additional evidence. Ask for the missing table FQN rather than guessing it.

## Workflow

1. From the repository root, read `AGENTS.md`, `docs/architecture/repository-structure.md`, and `references/evidence_policy.md` in this skill.
2. Fetch the current OpenMetadata table context through Teoria Admin API:

   ```bash
   python3 .agents/skills/analyze-metadata-asset/scripts/fetch_context.py \
     --table-fqn '<service.database.schema.table>' \
     --output /tmp/teoria_metadata_context.json
   ```

   Override `--admin-base-url` only when the Admin API is not at `http://localhost:8001`. This step is read-only. If OpenMetadata is unavailable, report that limitation and continue only when repository or user-provided evidence is sufficient.
3. Inspect only relevant evidence:
   - the selected table and column metadata;
   - existing ontology concepts and semantic bindings under `platform/`;
   - active Source Registry contracts and mappings when they establish field meaning;
   - user-provided or repository source documents;
   - bounded, read-only data samples only when the user authorized them and the registered Database Source supplies the query path.
4. Separate observations from inference. Do not infer authoritative meaning from a similar name alone. Prefer the semantic path `Physical Asset -> OpenMetadata Glossary Term -> Teoria Ontology`. Direct data-asset binding is supplemental.
5. Produce a bundle conforming to `references/proposal_bundle.schema.json`. Use one suggestion per independently reviewable change. Record the OpenMetadata version in evidence provenance and add content hashes for local documents when available.
6. Validate locally without submitting:

   ```bash
   python3 .agents/skills/analyze-metadata-asset/scripts/submit_proposals.py proposal_bundle.json
   ```

7. Show the user the proposed changes, evidence, confidence, warnings, and unsupported gaps. Submit only when the user asked to place proposals in the Review Queue:

   ```bash
   python3 .agents/skills/analyze-metadata-asset/scripts/submit_proposals.py \
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
- Do not create an Ontology concept merely to match a physical column. Propose a separate ontology-authoring task when durable business meaning is genuinely missing.

## Success criteria

- Every suggestion validates against the bundle contract.
- Every material claim has traceable evidence or is explicitly marked as inference.
- No OpenMetadata entity body is copied into Teoria persistence.
- The Review Queue contains only pending suggestions, with no automatic approval or application.
