from pydantic import Field

from teoria.models.common import IdentifiedModel, RegistryMetadata, RegistryModel


class ValueSetValue(IdentifiedModel):
    name: str
    description: str


class ValueSetDefinition(IdentifiedModel):
    name: str
    description: str
    values: list[ValueSetValue] = Field(min_length=1)


class ValueSetRegistry(RegistryModel):
    registry: RegistryMetadata
    value_sets: list[ValueSetDefinition]
