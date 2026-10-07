from pathlib import Path

import pytest
from pydantic import ValidationError

from teoria.registry.loader import RegistryLoadError, RegistryLoader
from teoria.registry.schema import ReferenceFile, RuntimeContractRegistry
from teoria.registry.validation.registry import RegistryValidator


REGISTRIES = Path(__file__).parents[3] / "registries"


def test_loads_current_registries() -> None:
    catalog = RegistryLoader(REGISTRIES).load()

    assert set(catalog.sources) == {
        "fsc_company_basic",
        "fsc_company_financial",
        "kodma_smpp_certificate",
        "mss_venture_company_disclosure",
        "mss_innobiz_company_lookup",
        "mss_mainbiz_company_lookup",
        "nts_business_registration",
        "pps_user",
        "teoria_public_procurement",
    }
    assert "business_registration_number" in catalog.data_types
    assert set(catalog.runtime_contracts) == {"assessment", "company", "public_procurement"}
    assert all(path.name == "runtime_contract.yaml" for path in catalog.runtime_contract_paths.values())
    assert "business_operating_status_kr" in catalog.value_sets
    assert "holds_valid_direct_production_confirmation" in catalog.eligibility_rules
    assert catalog.eligibility_rules["is_valid_women_owned_business"].evaluator == "qualification_valid"
    assert {
        source_id
        for source_id, reference in catalog.references.items()
        if reference.status == "active"
    } == {
        "fsc_company_basic",
        "fsc_company_financial",
        "kodma_smpp_certificate",
        "mss_venture_company_disclosure",
        "mss_innobiz_company_lookup",
        "mss_mainbiz_company_lookup",
        "nts_business_registration",
        "pps_user",
    }
    assert set(catalog.capabilities) == {
        "assess_company_bid_eligibilities",
        "assess_company_bid_eligibility",
            "analyze_company_competitors",
            "analyze_bid_participation_context",
            "analyze_organization_procurement_profile",
            "analyze_company_procurement_profile",
            "analyze_procurement_relationship_context",
            "summarize_procurement_relationship_graph",
            "search_procurement_relationship_graph_entities",
        "find_bid_project_lineage",
        "get_organization_company_relationship",
            "get_company_similar_project_experience",
            "get_bid_notice_relationship_context",
            "get_bid_notice_participations",
            "search_bid_related_projects",
        "get_business_registration_status",
        "get_company_financials",
        "get_company_detail_context",
        "get_company_profile",
        "get_company_relationships",
        "verify_innobiz_company",
        "verify_mainbiz_company",
        "verify_venture_company",
        "get_public_procurement_contract",
        "get_bid_notice_contracts",
        "search_bid_awards",
        "search_bid_participations",
            "search_public_procurement_contracts",
            "search_procurement_outcomes",
            "search_procurement_activity",
            "search_organization_supplier_entries",
            "search_public_organizations",
        "get_company_public_procurement_contracts",
        "search_companies_by_name",
        "resolve_company_identifiers",
        "search_bid_notices",
        "get_bid_notice",
            "get_bid_notices_by_ids",
            "get_bid_requirements",
            "get_bid_requirements_by_notice_ids",
            "get_bid_participation_findings",
            "get_procurement_supplier",
            "get_procurement_supplier_industries",
            "get_procurement_supplier_products",
            "get_procurement_supplier_sanctions",
            "get_company_procurement_profile",
            "get_company_qualifications",
            "get_direct_production_confirmations",
            "get_company_bid_qualification_profile",
        }


def test_runtime_contract_schema_rejects_the_removed_ontology_root_key() -> None:
    with pytest.raises(ValidationError):
        RuntimeContractRegistry.model_validate(
            {
                "registry": {"version": "1.0.0", "registered_at": "2026-10-06"},
                "ontology": {
                    "id": "legacy",
                    "name": "Legacy contract",
                    "description": "Compatibility document",
                    "object_types": [
                        {
                            "id": "item",
                            "name": "Item",
                            "description": "Compatibility object",
                            "primary_key": "id",
                            "properties": [
                                {"id": "id", "name": "ID", "description": "ID", "data_type": "string"}
                            ],
                        }
                    ],
                },
            }
        )


def test_current_registries_have_resolvable_references() -> None:
    catalog = RegistryLoader(REGISTRIES).load()

    assert RegistryValidator().validate(catalog) == []


def test_rejects_empty_registry_root(tmp_path: Path) -> None:
    with pytest.raises(RegistryLoadError) as exc_info:
        RegistryLoader(tmp_path).load()

    assert exc_info.value.diagnostics[0].code == "empty_registry"


def test_reports_missing_provider_reference_file() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    catalog.references["nts_business_registration"].files[0].path = "missing.md"

    diagnostics = RegistryValidator().validate(catalog)

    assert "reference_file_not_found" in {item.code for item in diagnostics}


def test_reference_file_uses_a_short_supported_format() -> None:
    reference = ReferenceFile(path="provider_document.docx", format="docx")

    assert reference.format == "docx"
    with pytest.raises(ValueError):
        ReferenceFile(path="provider_document.exe", format="exe")
