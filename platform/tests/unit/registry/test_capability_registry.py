from copy import deepcopy
from pathlib import Path

import pytest

from teoria.registry.loader import RegistryLoader
from teoria.registry.schema.capability import CapabilityDefinition
from teoria.registry.validator import RegistryValidator


REGISTRIES = Path(__file__).parents[3] / "registries"


def test_capabilities_load_and_references_are_valid() -> None:
    catalog = RegistryLoader(REGISTRIES).load()

    assert RegistryValidator().validate(catalog) == []
    capability = catalog.capabilities["get_company_profile"]
    assert capability.steps[0].call == "fsc_company_basic.get_company_overview"
    assert "company.legal_entity" in capability.returns
    search = catalog.capabilities["search_companies_by_name"]
    assert search.inputs["company_name"].property == "company.legal_entity.legal_name"
    assert search.steps[0].call == "fsc_company_basic.get_company_overview"
    assert search.kind == "query"
    assert search.effects.reads == []


def test_capability_inputs_are_semantic_ontology_references() -> None:
    catalog = RegistryLoader(REGISTRIES).load()

    verification = catalog.capabilities["verify_business_registration"]
    businesses = verification.inputs["businesses"]
    assert businesses.collection == "list"
    assert businesses.fields["business_registration_number"].property == (
        "company.business_registration.business_registration_number"
    )
    representative = businesses.fields["representative_name"]
    assert representative.property is None
    assert representative.data_type == "string"
    assert representative.field.endswith("request.body.businesses[].p_nm")


def test_capability_kind_distinguishes_compute_results_from_persisted_actions() -> None:
    common = {
        "id": "assess_company_bid_eligibility",
        "description": "입찰 참가자격을 평가한다.",
        "steps": [{"call": "teoria_public_procurement.bid_requirements"}],
        "returns": ["assessment.bid_eligibility_assessment"],
    }

    compute = CapabilityDefinition.model_validate(
        {
            **common,
            "kind": "compute",
            "processor": "assessment.evaluate_bid_eligibility",
            "effects": {
                "reads": ["public_procurement.bid_requirement"],
                "produces": ["assessment.bid_eligibility_assessment"],
            },
        }
    )
    assert compute.kind == "compute"
    assert compute.effects.produces == ["assessment.bid_eligibility_assessment"]

    with pytest.raises(ValueError, match="only an action capability"):
        CapabilityDefinition.model_validate(
            {
                **common,
                "kind": "compute",
                "processor": "assessment.evaluate_bid_eligibility",
                "effects": {"creates": ["assessment.bid_eligibility_assessment"]},
            }
        )


def test_reports_unknown_capability_effect_reference() -> None:
    catalog = deepcopy(RegistryLoader(REGISTRIES).load())
    capability = catalog.capabilities["get_bid_requirements"]
    capability.effects.reads = ["assessment.missing_object"]

    diagnostics = RegistryValidator().validate(catalog)

    assert "unknown_capability_effect" in {item.code for item in diagnostics}
