# AI-Native Metadata Platform target architecture

## Authority boundaries

- Prefect owns workflow and data operations.
- OpenMetadata owns technical metadata, governance metadata, glossary terms,
  ownership, data quality, usage, and physical lineage.
- Teoria owns Business Ontology, Semantic Binding, Metadata Intelligence,
  Capability semantics, and Context composition.
- OpenMetadata entities are referenced by ID/FQN/version and are not copied
  into the Teoria application database.

## Model boundaries

The legacy Ontology Registry contains both business concepts and Capability
response projections. Ontology v2 contains only durable business meaning.
Runtime response projections remain versioned API contracts.

The legacy Mapping Registry is a runtime transformation contract. It remains a
Runtime Mapping and must not be treated as an approved Semantic Binding.

```text
Runtime Mapping: source record -> runtime object
Semantic Binding: ontology concept <-> term, asset, API field, or capability
```

## Storage

```text
teoria_data       collected and normalized application data
teoria_app        ontology, binding, intelligence, and context configuration
openmetadata_db   OpenMetadata-owned metadata state
```

Published ontology versions are immutable. AI suggestions are not authoritative
until reviewed and successfully applied to OpenMetadata or the Teoria store.

## Initial vertical slice

```text
PostgreSQL column
  -> OpenMetadata Column + Glossary Term
  -> Teoria MetadataTargetRef (non-owning value object)
  -> OntologyBinding
  -> Contract.amount
  -> Context Engine (future)
```

`MetadataTargetRef` is not a Teoria metadata entity and must never grow into a
metadata cache. It contains only the external system, entity ID, entity type,
FQN, and optional version needed to resolve the authoritative OpenMetadata
entity. The relational `binding.metadata_targets` table is a normalized storage
form of that value object, not a catalog.

## Semantic paths

The preferred semantic path uses OpenMetadata Business Terms as the shared
vocabulary:

```text
Physical Asset (OpenMetadata Column)
  -> assigned OpenMetadata Glossary Term
  -> OntologyBinding(target_type=glossary_term, preferred)
  -> Teoria Ontology Property
```

Direct bindings remain valid when a term does not add value or has not yet been
approved:

```text
OpenMetadata Data Asset -> OntologyBinding(target_type=data_asset) -> Ontology
Provider API Field      -> OntologyBinding(target_type=api_field)  -> Ontology
Teoria Capability       -> OntologyBinding(target_type=capability) -> Ontology
```

An API field binding can only be approved after the active Source Registry
contract verifies the provider's original field. Similar names are not enough.

## Independent knowledge sources

Business Ontology, OpenMetadata, and Capabilities are independent knowledge
sources. Semantic Binding connects them; none is a child or copy of another.

```text
                              AI Agent
                                 ^
                           MCP / API / SDK
                                 |
                          Context Engine
                                 |
        +------------------------+------------------------+
        |                        |                        |
 Business Ontology         OpenMetadata             Capabilities
        |              Technical + Semantic              |
        +---------------- Semantic Binding ---------------+
                                 ^
                      Metadata Intelligence
                        Suggest / Review
                         /             \
                OpenMetadata        Teoria App DB
```

For example, resolving `Contract.amount` can yield three different answers:

- Meaning: OpenMetadata Glossary Term `계약금액`
- Analytical location: OpenMetadata Column
  `public_procurement.contracts.current_contract_amount`
- Live retrieval: an approved Capability binding to a verified Provider API
  operation and response field

Runtime Mapping is still responsible for executing `source record -> runtime
object`; it is not an OntologyBinding.

## Stable phase contracts

The following identities and value contracts are fixed before broader Phase 2
features are added:

- `BusinessObjectId`, `OntologyPropertyId`
- `OntologyVersion`, `OntologyStatus`
- `OntologyBinding`
- `MetadataTargetRef`, `ApiFieldTargetRef`, `CapabilityTargetRef`
- `SuggestionTarget`, `Evidence`, `Provenance`

Target references carry only resolution coordinates and contract versions.
Descriptions, owners, tags, schemas, and other OpenMetadata state are fetched
from OpenMetadata when needed and are not persisted as target snapshots.

The current foundation provides the deployment boundary, REST metadata gateway,
Admin metadata explorer, versioned Ontology authoring, stable Semantic Binding,
review governance, immutable runtime artifacts, and domain contracts.

## Metadata Intelligence review slice

The first Intelligence workflow supports low-risk OpenMetadata table
description suggestions:

```text
Suggestion(pending) + Evidence
  -> Human Review
  -> approved
  -> OpenMetadata JSON Patch
  -> ChangeApplication(applied|failed)
  -> Suggestion(applied|failed)
```

- Suggestions and review evidence are Teoria-owned application state.
- A pending suggestion never changes authoritative metadata.
- Rejected suggestions are retained for audit.
- Only low-risk table description changes are automatically applied after
  approval in this phase.
- Glossary mappings, Ontology Bindings, metrics, rules, policies, and ontology
  structural changes require later risk-specific approval policies.
- OpenMetadata remains the authoritative source after successful write-back;
  Teoria stores the suggestion, review, and external change reference rather
  than a second copy of the table metadata.

Ontology authoring and governed Binding review are implemented. Intelligence
generation and the Context Engine remain the next product phases. The current
API accepts suggestions produced by a future AI job or another trusted internal
producer; the next vertical slice generates an evidence-backed Binding
Suggestion from an OpenMetadata Column.
