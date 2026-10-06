from __future__ import annotations

from typing import Any

from teoria.registry.loader import RegistryCatalog


class ApiFieldContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def resolve_api_field_contract(
    catalog: RegistryCatalog,
    *,
    source_id: str,
    operation_id: str,
    object_id: str,
    field_path: str,
) -> dict[str, Any]:
    source_registry = catalog.sources.get(source_id)
    if source_registry is None or source_registry.source.type != "api":
        raise ApiFieldContractError("unknown_api_source")
    source = source_registry.source
    operation = next((item for item in source.operations if item.id == operation_id), None)
    if operation is None:
        raise ApiFieldContractError("unknown_source_operation")
    if operation.response.data.ref != object_id:
        raise ApiFieldContractError("operation_response_object_mismatch")
    response_object = next((item for item in source.components.objects if item.id == object_id), None)
    field = next(
        (item for item in response_object.fields if item.id == field_path),
        None,
    ) if response_object else None
    if field is None:
        raise ApiFieldContractError("unknown_response_field")
    return {
        "source_id": source_id,
        "operation_id": operation_id,
        "object_id": object_id,
        "field_path": field_path,
        "field_name": field.name,
        "data_type": field.data_type,
        "contract_version": source_registry.registry.version,
    }
