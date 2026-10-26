# Independent backend fixtures

`registry/` and `references/` define a synthetic API and database contract for platform
regressions. They exercise transport, schema validation, mapping, materialization,
authentication, authorization, versioning and semantic bindings without depending on
retired business registries or reactivating their capabilities.

`server_specifications.py` defines explicit synthetic source observations and package
identities. These are deterministic query and pipeline controls, not model accuracy
labels. The compact real source control under `features/goods_querying/fixtures/`
retains its source checksum and silver status separately.
