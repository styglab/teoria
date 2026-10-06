from uuid import uuid4

from teoria.binding.models import OntologyBinding


def _binding(target: dict) -> OntologyBinding:
    return OntologyBinding(
        id=uuid4(), ontology_ref_type="property", ontology_ref_id=uuid4(),
        target=target, binding_type="represents", created_by="test",
    )


def test_openmetadata_target_is_a_non_owning_reference() -> None:
    binding = _binding({
        "target_type": "glossary_term", "system": "openmetadata",
        "entity_id": "term-1", "entity_type": "glossaryTerm",
        "fully_qualified_name": "Procurement.ContractAmount", "version": "0.1",
    })
    assert binding.target.system == "openmetadata"
    assert not hasattr(binding.target, "description")


def test_api_and_capability_targets_are_explicit_contract_refs() -> None:
    api_binding = _binding({
        "target_type": "api_field", "source_id": "pps_contract",
        "operation_id": "get_contract", "object_id": "contract",
        "field_path": "amount",
        "contract_version": "2026-01",
    })
    capability_binding = _binding({
        "target_type": "capability_output", "capability_id": "get_contract",
        "field_path": "objects[].amount", "contract_version": "1.0",
    })
    assert api_binding.target.system == "provider"
    assert capability_binding.target.system == "teoria"
