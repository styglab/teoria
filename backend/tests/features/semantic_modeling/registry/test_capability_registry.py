from copy import deepcopy
from pathlib import Path

import pytest

from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.features.semantic_modeling.registry.schema.capability import CapabilityDefinition
from teoria.features.semantic_modeling.registry.validation.registry import RegistryValidator


REGISTRIES = Path("archive/procurement_services/platform/registries")


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
    resolver = catalog.capabilities["resolve_company_identifiers"]
    assert resolver.kind == "compute"
    assert resolver.processor == "company_identity.resolve_company_identifiers"
    assert resolver.inputs["business_registration_number"].required is True
    assert resolver.inputs["company_name"].required is True
    detail = catalog.capabilities["get_company_detail_context"]
    assert detail.kind == "compute"
    assert detail.processor == "company_identity.get_company_detail_context"
    assert detail.inputs["financial_year_limit"].default == 3
    assert detail.inputs["financial_lookback_years"].default == 7
    assert catalog.capabilities["search_bid_awards"].steps[0].call == (
        "teoria_public_procurement.bid_awards"
    )
    assert catalog.capabilities["search_bid_participations"].processor == (
        "market_context.search_company_bid_participations"
    )
    assert catalog.capabilities["get_bid_notice_participations"].processor == (
        "market_context.get_bid_notice_participations"
    )


def test_capability_kind_distinguishes_compute_results_from_persisted_actions() -> None:
    common = {
        "id": "compute_company_profile",
        "description": "입찰 참가자격을 평가한다.",
        "steps": [{"call": "fsc_company_basic.get_company_overview"}],
        "returns": ["company.legal_entity"],
    }

    compute = CapabilityDefinition.model_validate(
        {
            **common,
            "kind": "compute",
            "processor": "company_identity.compute_profile",
            "effects": {
                "reads": ["company.business_registration"],
                "produces": ["company.legal_entity"],
            },
        }
    )
    assert compute.kind == "compute"
    assert compute.effects.produces == ["company.legal_entity"]

    with pytest.raises(ValueError, match="only an action capability"):
        CapabilityDefinition.model_validate(
            {
                **common,
                "kind": "compute",
                "processor": "company_identity.compute_profile",
                "effects": {"creates": ["company.legal_entity"]},
            }
        )


def test_reports_unknown_capability_effect_reference() -> None:
    catalog = deepcopy(RegistryLoader(REGISTRIES).load())
    capability = catalog.capabilities["get_bid_notice"]
    capability.effects.reads = ["assessment.missing_object"]

    diagnostics = RegistryValidator().validate(catalog)

    assert "unknown_capability_effect" in {item.code for item in diagnostics}
