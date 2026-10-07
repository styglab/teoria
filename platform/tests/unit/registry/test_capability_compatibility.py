from pathlib import Path

from teoria.ontology.blueprint import OntologyBlueprint
from teoria.registry.compatibility import validate_capability_compatibility
from teoria.registry.loader import RegistryLoader
from teoria.registry.schema.capability import (
    CapabilitySemanticRequirements,
    SemanticRequirement,
)


REGISTRIES = Path(__file__).parents[3] / "registries"
ONTOLOGY_BLUEPRINT = (
    Path(__file__).parents[3]
    / "ontology_migrations"
    / "applied"
    / "2026_10_initial_unification"
    / "teoria_business_ontology_v1.yaml"
)


def _published_ontology_from_blueprint() -> dict:
    blueprint = OntologyBlueprint.load(ONTOLOGY_BLUEPRINT)
    return {
        "content": {
            "objects": [item.model_dump(mode="json") for item in blueprint.objects],
            "relationships": [
                item.model_dump(mode="json") for item in blueprint.relationships
            ],
        }
    }


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


def test_search_bid_notices_is_compatible_with_target_ontology_blueprint() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    capability = catalog.capabilities["search_bid_notices"]

    report = next(
        item
        for item in validate_capability_compatibility(
            catalog, [_published_ontology_from_blueprint()]
        )
        if item["capability_id"] == capability.id
    )

    assert capability.version == "1.7.0"
    assert report["semantic_requirements_declared"] is True
    assert report["status"] == "compatible"
    assert report["missing_required"] == []
    assert report["unresolved_optional"] == []
    assert {
        (item["kind"], item["stable_key"]) for item in report["resolved"]
    } == {
        ("concept", "procurement.BidNotice"),
        ("concept", "procurement.Organization"),
        ("property", "procurement.BidNotice.bidNoticeId"),
        ("property", "procurement.BidNotice.noticeName"),
        ("property", "procurement.BidNotice.publishedAt"),
        ("property", "procurement.BidNotice.deadlineAt"),
        ("property", "procurement.BidNotice.status"),
        ("property", "procurement.Organization.organizationCode"),
        ("property", "procurement.Organization.name"),
        ("relationship", "procurement.PUBLISHES"),
    }


def test_get_bid_notice_is_compatible_with_target_ontology_blueprint() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    capability = catalog.capabilities["get_bid_notice"]

    report = next(
        item
        for item in validate_capability_compatibility(
            catalog, [_published_ontology_from_blueprint()]
        )
        if item["capability_id"] == capability.id
    )

    assert capability.version == "1.0.0"
    assert report["semantic_requirements_declared"] is True
    assert report["status"] == "compatible"
    assert report["missing_required"] == []
