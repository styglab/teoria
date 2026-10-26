from pathlib import Path

import pytest
from pydantic import ValidationError

from teoria.features.semantic_modeling.registry.loader import RegistryLoadError, RegistryLoader
from teoria.features.semantic_modeling.registry.schema import ReferenceFile, RuntimeContractRegistry
from teoria.features.semantic_modeling.registry.validation.registry import RegistryValidator


REGISTRIES = Path("backend/tests/fixtures/registry")




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
    catalog.references["example_api"].files[0].path = "missing.md"

    diagnostics = RegistryValidator().validate(catalog)

    assert "reference_file_not_found" in {item.code for item in diagnostics}


def test_reference_file_uses_a_short_supported_format() -> None:
    reference = ReferenceFile(path="provider_document.docx", format="docx")

    assert reference.format == "docx"
    with pytest.raises(ValueError):
        ReferenceFile(path="provider_document.exe", format="exe")


def test_loads_small_independent_contract_fixture():
    catalog = RegistryLoader(REGISTRIES).load()
    assert set(catalog.sources) == {"example_api", "example_data"}
    assert set(catalog.runtime_contracts) == {"example"}
    assert set(catalog.capabilities) == {"search_records", "get_record"}
    assert catalog.runtime_contract_paths["example"].parent.name == "runtime_contracts"
