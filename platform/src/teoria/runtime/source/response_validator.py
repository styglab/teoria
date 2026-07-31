from teoria_provider.models import ExecutionResponse
from teoria_provider.response_validator import ProviderResponseValidator

from teoria.registry.loader import RegistryCatalog


class SourceResponseValidator:
    """Platform adapter from a RegistryCatalog to provider response validation."""

    def validate(self, catalog: RegistryCatalog, source_id: str, operation_id: str,
                 response: ExecutionResponse):
        registry = catalog.sources[source_id]
        return ProviderResponseValidator().validate(registry.source, operation_id, response,
            data_types=catalog.data_types, path=catalog.source_paths[source_id])


__all__ = ["SourceResponseValidator"]
