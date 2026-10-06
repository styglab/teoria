from teoria_provider_api.schema import ContractMetadata, ContractModel, ProviderDefinition


class ConnectorRegistry(ContractModel):
    """An upstream API contract used by an ingestion pipeline, not by Runtime."""

    registry: ContractMetadata
    connector: ProviderDefinition
