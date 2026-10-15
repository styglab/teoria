---
name: analyze-metadata-asset
description: Compatibility entrypoint for existing Teoria metadata analysis requests. Routes description and glossary work to enrich-metadata-asset and existing Ontology bindings to align-metadata-semantics.
---

# Metadata analysis compatibility

Existing `$analyze-metadata-asset` requests remain supported. Read the relevant
current skill rather than reimplementing its workflow:

- Descriptions and glossary: [메타데이터 정비](../enrich-metadata-asset/SKILL.md).
- Existing published Ontology bindings: [업무 의미 연결](../align-metadata-semantics/SKILL.md).
- Legal disclosure diagnosis: [개방 적합성 진단](../assess-data-disclosure/SKILL.md).

Preserve the user's requested table, scope and submission authorization when
routing. New Ontology authoring is deferred. Never approve or apply suggestions.
