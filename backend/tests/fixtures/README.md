# Independent backend fixtures

`registry/` and `references/` define a synthetic API and database contract for platform
regressions. They exercise transport, schema validation, mapping, materialization,
authentication, authorization, versioning and semantic bindings without depending on
retired business registries or reactivating their capabilities.

The retired server-memory comparison fixtures were removed with that feature. Generic
specification extraction and normalization controls remain with their owning feature tests.
