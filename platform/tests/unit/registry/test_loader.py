from pathlib import Path

import pytest

from teoria.registry.loader import RegistryLoadError, RegistryLoader
from teoria.registry.schema import ReferenceFile
from teoria.registry.validator import RegistryValidator


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
    assert set(catalog.ontologies) == {"assessment", "company", "public_procurement"}
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
        "assess_company_bid_eligibility",
        "get_business_registration_status",
        "get_company_financials",
        "get_company_profile",
        "get_company_relationships",
        "verify_business_registration",
        "verify_innobiz_company",
        "verify_mainbiz_company",
        "verify_venture_company",
        "get_public_procurement_contract",
        "search_public_procurement_contracts",
        "get_company_public_procurement_contracts",
        "search_companies_by_name",
        "search_bid_notices",
        "get_bid_notice",
            "get_bid_requirements",
            "get_demand_organization",
            "get_procurement_supplier",
            "get_procurement_supplier_industries",
            "get_procurement_supplier_products",
            "get_procurement_supplier_sanctions",
            "get_company_procurement_profile",
            "get_women_owned_business_qualification",
            "get_disabled_owned_business_qualification",
            "get_company_qualifications",
            "get_direct_production_confirmations",
            "get_company_bid_qualification_profile",
        }


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
