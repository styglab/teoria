from pathlib import Path
from typing import Any

from teoria_provider.diagnostics import Diagnostic
from teoria_provider.request_builder import ProviderRequestBuilder, RequestBuildError

from teoria.registry.loader import RegistryCatalog


class SourceRequestBuilder:
    """Platform adapter from a RegistryCatalog to the shared provider builder."""

    def build(self, catalog: RegistryCatalog, source_id: str, operation_id: str,
              input_data: dict[str, Any]):
        path = catalog.source_paths.get(source_id, catalog.root / "sources")
        registry = catalog.sources.get(source_id)
        if registry is None:
            raise RequestBuildError([Diagnostic("unknown_source", f"unknown source '{source_id}'", path)])
        if registry.source.type != "api":
            raise RequestBuildError([Diagnostic("unsupported_source_operation",
                f"source '{source_id}' is a database source and cannot build an HTTP request", path)])
        return ProviderRequestBuilder().build(registry.source, operation_id, input_data,
            data_types=catalog.data_types, path=Path(path))


__all__ = ["RequestBuildError", "SourceRequestBuilder"]
