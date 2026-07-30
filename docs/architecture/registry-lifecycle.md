# Registry lifecycle

Authored YAML is the source of truth during the initial Git-backed phase. Runtime services execute only a validated, immutable publication in production.

```text
draft -> validate -> review -> approve -> publish -> deprecate
```

A publication produces a bundle containing the resolved catalog, graph projection, manifest and checksums. Its manifest records the bundle ID, creation time, Git commit, schema version, runtime compatibility and transform code version.

Every execution must pin one bundle for its entire lifetime and add the bundle ID and runtime version to provenance and audit data. A new publication affects new executions only.

Published identifiers are stable. Definitions are deprecated instead of silently deleted, and incompatible changes require a new content version. Registry schema version, definition content version and published bundle version are separate concepts.

Console edits create drafts. They do not overwrite a published filesystem tree. Validation, impact analysis and review precede publication; credentials remain secret references and are never written into registry YAML.
