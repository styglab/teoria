from pathlib import Path

from teoria.registry.compatibility import validate_capability_compatibility
from teoria.registry.loader import RegistryLoader
from teoria.registry.schema.capability import (
    CapabilitySemanticRequirements,
    SemanticRequirement,
)


REGISTRIES = Path(__file__).parents[3] / "registries"


def test_loader_materializes_capability_version_and_definition_checksum() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    capability = catalog.capabilities["assess_company_bid_eligibility"]

    assert capability.version == "1.2.0"
    assert catalog.capability_versions[(capability.id, capability.version)] is capability
    assert catalog.capability_checksums[(capability.id, capability.version)].startswith(
        "sha256:"
    )


def test_compatibility_is_computed_for_a_specific_capability_version() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    capability_id = "assess_company_bid_eligibility"
    original = catalog.capabilities[capability_id]
    capability = original.model_copy(update={
        "semantic_requirements": CapabilitySemanticRequirements(
            concepts=[SemanticRequirement(stable_key="party.BusinessEntity")],
            properties=[SemanticRequirement(
                stable_key="party.BusinessRegistration.businessRegistrationNumber"
            )],
        )
    })
    catalog.capabilities[capability_id] = capability
    catalog.capability_versions[(capability_id, capability.version)] = capability
    ontology = {
        "content": {
            "objects": [{
                "stable_key": "party.BusinessEntity",
                "concept_id": "object-id",
                "properties": [],
            }],
            "relationships": [],
        }
    }

    report = next(
        item for item in validate_capability_compatibility(catalog, [ontology])
        if item["capability_id"] == capability_id
    )

    assert report["capability_version"] == "1.2.0"
    assert report["status"] == "incompatible"
    assert report["missing_required"] == [{
        "kind": "property",
        "stable_key": "party.BusinessRegistration.businessRegistrationNumber",
        "semantic_id": None,
    }]
