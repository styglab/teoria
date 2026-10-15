# Metadata suggestion evidence policy

## Evidence precedence

Use the strongest applicable evidence first:

1. Provider specification or governing source document tied to the exact field.
2. Active Source Registry operation and verified response field.
3. Existing OpenMetadata Glossary Term with stewarded description.
4. Published Teoria Ontology concept and approved Semantic Binding.
5. OpenMetadata description, owner, tags, lineage, and quality results.
6. Bounded data profile or sample from a registered read-only source.
7. Field-name similarity.

Levels 6 and 7 support discovery but do not establish authoritative meaning alone.

## Required evidence behavior

- Cite repository evidence as a path plus stable identifier or line where practical.
- Cite OpenMetadata evidence with `openmetadata://<entity_type>/<FQN>` and record entity version in `provenance.source_version`.
- Hash local source documents with SHA-256 when they materially support a proposal.
- Preserve disagreement between sources in `warnings`; do not silently select one.
- Avoid raw row values in proposal artifacts. Use aggregate type/null/distinct/range observations and redact sensitive examples.

## Confidence guide

- `0.90-1.00`: exact authoritative definition plus compatible published concept.
- `0.75-0.89`: multiple consistent governed sources with no material conflict.
- `0.50-0.74`: plausible but incomplete evidence; require careful review.
- Below `0.50`: do not submit unless the user explicitly wants low-confidence discovery candidates.

Confidence does not authorize application.

## Stop conditions

Stop and report `needs_evidence` when the field cannot be tied to a source contract or governed business definition. Stop and report `conflict` when authoritative sources disagree. Never fabricate a glossary FQN, OpenMetadata entity ID, ontology stable ID, version, owner, or quality result.
