from typing import Any, Literal

from pydantic import Field, model_validator

from teoria.registry.schema.common import IdentifiedModel, RegistryMetadata, RegistryModel


class RuntimeContractProperty(IdentifiedModel):
    name: str
    description: str
    data_type: str | None = None
    value_set: str | None = None
    collection: Literal["scalar", "list"] = "scalar"

    @model_validator(mode="after")
    def exactly_one_value_type(self) -> "RuntimeContractProperty":
        if (self.data_type is None) == (self.value_set is None):
            raise ValueError("property must declare exactly one of data_type or value_set")
        return self


class RuntimeContractObjectType(IdentifiedModel):
    name: str
    description: str
    primary_key: str
    examples: list[dict[str, Any]] = Field(default_factory=list)
    properties: list[RuntimeContractProperty] = Field(min_length=1)


class RuntimeContractLinkType(IdentifiedModel):
    description: str
    source: str
    target: str


class RuntimeContractDefinition(IdentifiedModel):
    name: str
    description: str
    object_types: list[RuntimeContractObjectType] = Field(min_length=1)
    link_types: list[RuntimeContractLinkType] = Field(default_factory=list)


class RuntimeContractRegistry(RegistryModel):
    registry: RegistryMetadata
    runtime_contract: RuntimeContractDefinition
