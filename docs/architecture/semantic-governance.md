# Semantic governance

## Authority boundary

- OpenMetadata owns technical, governance, and semantic metadata.
- Teoria owns durable Business Ontology, Semantic Binding, Intelligence review
  records, Capability semantics, and future Context composition.
- Metadata targets in Teoria are references (`system`, external ID, entity type,
  FQN, optional version), not copied metadata entities.

The preferred route is physical asset → OpenMetadata Glossary Term → Teoria
Ontology. Direct asset bindings remain supported. API fields and Capabilities are
independent binding targets rather than catalog entities.

## Binding lifecycle

```text
draft ──approve──▶ approved ──deprecate──▶ deprecated
   └──reject────▶ rejected
```

Review records are append-only. An active ontology-target pair cannot have duplicate
draft/approved bindings.

## Risk roles

| Change | Risk | Required role |
|---|---:|---|
| Description suggestion/create | low | `metadata_admin` |
| Description approval/write-back | low | `metadata_reviewer` or `metadata_admin` |
| Glossary/data-asset binding | medium | `binding_reviewer` or `metadata_admin` |
| Ontology structural change | high | `ontology_owner` |

The initial bearer implementation is an authentication boundary, not a complete
identity system. It can later be replaced by OIDC without moving authorization
rules into domain modules.

## Procurement Ontology v2

Version `0.3.0` is the current published reference model and contains durable
business meaning only:

- `Organization`, `Company`, `BidNotice`, `Award`, `Contract`
- `PUBLISHES`, `RESULTS_IN_AWARD`, `AWARDED_TO`, `RESULTS_IN_CONTRACT`,
  `SIGNS`, `CONTRACTOR`
- stable identifiers, `Contract.amount`, `Contract.contractDate`, and `Award.amount`

Runtime response DTOs and provider wire fields are excluded. Their connection to
the ontology belongs in Runtime Mapping or Semantic Binding.
