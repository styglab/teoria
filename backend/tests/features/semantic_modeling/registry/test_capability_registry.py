from copy import deepcopy
from pathlib import Path

import pytest

from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.features.semantic_modeling.registry.schema.capability import CapabilityDefinition
from teoria.features.semantic_modeling.registry.validation.registry import RegistryValidator


REGISTRIES = Path("backend/tests/fixtures/registry")




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
    capability = catalog.capabilities["get_record"]
    capability.effects.reads = ["assessment.missing_object"]

    diagnostics = RegistryValidator().validate(catalog)

    assert "unknown_capability_effect" in {item.code for item in diagnostics}


def test_list_input_defaults_validate_each_enum_member():
    from teoria.features.semantic_modeling.registry.schema.capability import CapabilityInput
    definition = CapabilityInput(data_type="string", collection="list", enum=["eq", "gte"], default=["eq", "gte"])
    assert definition.default == ["eq", "gte"]
    for value in [["invented"], "eq"]:
        with pytest.raises(ValueError, match="input default"):
            CapabilityInput(data_type="string", collection="list", enum=["eq"], default=value)
