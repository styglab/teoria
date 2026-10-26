---
name: assess-data-disclosure
description: Draft evidence-backed information classification and external disclosure assessments for OpenMetadata assets using collected Korean law snapshots. Use for disclosure risk and protection recommendations; current output is a review report, not automatic tagging.
---

# 개방 적합성 진단

Require a table FQN. Establish the assessment date and intended disclosure
scenario (public release, restricted sharing, or another explicit context).
When context is unknown, report conditional findings and missing information.
Read `AGENTS.md`, `docs/architecture/repository-structure.md` and
[evidence policy](../enrich-metadata-asset/references/evidence_policy.md).

1. Read current descriptions, schema, tags and glossary with
   `../enrich-metadata-asset/scripts/fetch_context.py`. Profile and sample access
   contracts are in `backend/src/teoria/features/metadata_management/catalog/admin_router.py`. Use bounded
   authorized observations; do not persist raw sample values or send raw personal
   identifiers to an external model. Pattern matches are detection candidates.
2. Generate search keywords from observed information types. Use the collected
   law database via `POST /v1/admin/legal-information/search` with the assessment
   date and `version_scope: as_of`. Read the actual request contract in
   `backend/src/teoria/features/legal_information/search.py`.
3. Fetch relevant text with
   `GET /v1/admin/legal-information/documents/{snapshot_id}?path=...`.
   Inspect applicable conditions, exceptions and referenced provisions. If the
   text is truncated or a version is unavailable, record the gap; do not infer a
   legal conclusion from a search excerpt. Existing local snapshots are preferred;
   if official web verification is needed, explicitly cite that separate source.
4. Evaluate information type, internal processing basis, external disclosure
   context and recommended protection separately. Unknown legal basis means
   review required, not proof of illegality. Pseudonymization or masking alone
   does not establish suitability for public release. Identify policy rules by
   version only when approved rules actually exist.
5. Return a review report per asset/column containing observed metadata version,
   information-type candidates, detection evidence, legal candidates and reasons,
   internal-processing review status, disclosure recommendation, proposed tag
   candidates, protection recommendations, uncertainties and confidence. Pin each
   local citation to law ID, version/MST, effective date, snapshot ID, provision
   path, content hash when available and assessment date. Keep
   `legal_applicability_confirmed: false` for the AI draft.

The current Suggestion API has no `disclosure_assessment` or `tag_assignment`
application handler. Produce a report and mark tag candidates as proposals;
do not submit unsupported types or disguise legal findings as descriptions.
Verify actual OpenMetadata classifications and tag FQNs before suggesting an
assignment to an existing tag. Missing classifications are vocabulary gaps.
Never create tags, approve a finding, or patch OpenMetadata in this skill.
