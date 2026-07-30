from pathlib import Path

import pytest
from pydantic import ValidationError

from teoria.models import DataTypeDefinition, SourceRegistry
from teoria.registry.loader import RegistryCatalog, RegistryLoader
from teoria.registry.validator import RegistryValidator


def source_document() -> dict:
    return {
        "registry": {"version": "1.0.0", "registered_at": "2026-07-28"},
        "source": {
            "id": "example_source",
            "name": "Example",
            "provider": {"organization": "Example"},
            "type": "api",
            "specification": {"format": "manual", "version": "1.0"},
            "access": {
                "base_url": "https://example.com",
                "authentication": {
                    "type": "api_key",
                    "in": "query",
                    "name": "serviceKey",
                    "credential_env": "EXAMPLE_SERVICEKEY",
                },
            },
            "components": {
                "objects": [
                    {
                        "id": "item",
                        "fields": [{"id": "code", "data_type": "code"}],
                    }
                ]
            },
            "operations": [
                {
                    "id": "get_items",
                    "method": "GET",
                    "path": "/items",
                    "request": {
                        "query": {
                            "fields": [{"id": "limit", "data_type": "integer", "default": 10}],
                            "required": ["limit"],
                        }
                    },
                    "response": {
                        "content_type": "application/json",
                        "http_status": 200,
                        "data": {"record_path": "data[]", "ref": "item"},
                    },
                }
            ],
        },
    }


def catalog_for(document: dict, path: str = "registries/sources/example_source.yaml") -> RegistryCatalog:
    source = SourceRegistry.model_validate(document)
    data_type_definition = DataTypeDefinition(id="code", base_type="string", pattern="^[A-Z]+$")
    return RegistryCatalog(
        root=Path("registries"),
        sources={source.source.id: source},
        source_paths={source.source.id: Path(path)},
        data_types={data_type_definition.id: data_type_definition},
    )


def test_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text("source:\n  id: first\n  id: second\n", encoding="utf-8")
    diagnostics = []

    assert RegistryLoader._parse(path, diagnostics) is None
    assert diagnostics[0].code == "invalid_yaml"
    assert "duplicate key" in diagnostics[0].message


def test_model_rejects_invalid_array_shape_and_unknown_keys() -> None:
    document = source_document()
    field = document["source"]["components"]["objects"][0]["fields"][0]
    field["type"] = "array"
    field.pop("data_type")

    with pytest.raises(ValidationError) as exc_info:
        SourceRegistry.model_validate(document)

    assert "array field must declare items" in str(exc_info.value)

    document = source_document()
    document["source"]["components"]["objects"][0]["fields"][0]["unknown_option"] = True
    with pytest.raises(ValidationError) as exc_info:
        SourceRegistry.model_validate(document)

    assert "Extra inputs are not permitted" in str(exc_info.value)


def test_reports_cross_registry_and_semantic_errors() -> None:
    document = source_document()
    source = document["source"]
    source["components"]["objects"][0]["fields"][0]["data_type"] = "missing_data_type"
    operation = source["operations"][0]
    operation["request"]["query"]["required"] = ["missing", "missing"]
    operation["response"]["data"]["record_path"] = "data[0]"
    operation["response"]["data"]["ref"] = "missing_object"

    diagnostics = RegistryValidator().validate(catalog_for(document, "registries/sources/wrong_name.yaml"))
    codes = {diagnostic.code for diagnostic in diagnostics}

    assert {
        "source_filename_mismatch",
        "unknown_data_type",
        "duplicate_required_field",
        "unknown_required_field",
        "invalid_record_path",
        "unknown_ref",
    } <= codes


def test_can_validate_one_source() -> None:
    catalog = catalog_for(source_document())

    assert RegistryValidator().validate(catalog, source_id="example_source") == []
    assert RegistryValidator().validate(catalog, source_id="missing")[0].code == "unknown_source"
