from pathlib import Path

from teoria.registry.loader import RegistryLoader
from teoria.registry.validator import RegistryValidator


REGISTRIES = Path(__file__).parents[2] / "registries"


def test_loads_current_registries() -> None:
    catalog = RegistryLoader(REGISTRIES).load()

    assert set(catalog.sources) == {
        "fsc_company_basic",
        "fsc_company_financial",
        "nts_business_registration",
    }
    assert "business_registration_number" in catalog.formats


def test_current_registries_have_resolvable_references() -> None:
    catalog = RegistryLoader(REGISTRIES).load()

    assert RegistryValidator().validate(catalog) == []

