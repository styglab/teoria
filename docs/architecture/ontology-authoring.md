# Ontology authoring and publication

## Identity and revisions

`ontology.concepts` owns stable semantic identity. Business Object, Property,
Relationship, Rule, and Metric rows are version-scoped revisions. A Binding points
to the stable concept and retains its legacy revision reference during migration.

```text
Contract.amount (stable concept)
  ├─ revision in 0.2.0
  └─ revision in 0.3.0
```

Revision UUID changes alone never constitute a semantic diff.

## Lifecycle

```text
draft → in_review → approved → published → deprecated
           └────────→ draft
approved ───────────→ draft
```

- Only drafts are editable.
- Submission and approval require successful structural and Binding compatibility
  validation.
- Publishing creates a deterministic JSON runtime artifact and checksum.
- Publishing and deprecating the previous version happen in one transaction.
- PostgreSQL triggers prevent revision writes outside a draft version.

## Runtime boundary

The authoring relational model is not a Runtime contract. Runtime consumes the
immutable artifact produced from a published version. Existing Registry artifacts
remain supported while the compiler/adapter migration is completed.

## API

The `/v1/admin/ontology-authoring` boundary supports version history, draft cloning,
creation of all five concept kinds, validation, Binding impact, semantic diff, audit,
review transitions, approval, and publication. All mutations require
`ontology_owner`; the authenticated principal is written to the audit log.
