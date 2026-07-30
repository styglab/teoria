from pathlib import Path

import pytest

from teoria.registry.loader import RegistryLoadError, RegistryLoader
from teoria.registry.validator import RegistryValidator


REGISTRIES = Path(__file__).parents[3] / "registries"


def test_loads_current_registries() -> None:
    catalog = RegistryLoader(REGISTRIES).load()

    assert set(catalog.sources) == {
        "fsc_company_basic",
        "fsc_company_financial",
        "nts_business_registration",
    }
    assert "business_registration_number" in catalog.data_types
    assert set(catalog.ontologies) == {"company"}
    assert "business_operating_status_kr" in catalog.value_sets
    assert set(catalog.references) == set(catalog.sources)
    assert set(catalog.capabilities) == {
        "get_business_registration_status",
        "get_company_financials",
        "get_company_profile",
        "get_company_relationships",
        "verify_business_registration",
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
