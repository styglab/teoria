from pathlib import Path

from teoria.registry.loader import RegistryLoader
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
