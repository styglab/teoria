from typing import Any, Literal

from pydantic import Field, model_validator

from teoria.registry.schema.common import IdentifiedModel, RegistryMetadata, RegistryModel


class OntologyProperty(IdentifiedModel):
    name: str
    description: str
    data_type: str | None = None
    value_set: str | None = None
    collection: Literal["scalar", "list"] = "scalar"

    @model_validator(mode="after")
    def exactly_one_value_type(self) -> "OntologyProperty":
        if (self.data_type is None) == (self.value_set is None):
            raise ValueError("property must declare exactly one of data_type or value_set")
        return self


class OntologyObjectType(IdentifiedModel):
    name: str
    description: str
    primary_key: str
    examples: list[dict[str, Any]] = Field(default_factory=list)
    properties: list[OntologyProperty] = Field(min_length=1)


class OntologyLinkType(IdentifiedModel):
    description: str
    source: str
    target: str


class OntologyDefinition(IdentifiedModel):
    name: str
    description: str
    object_types: list[OntologyObjectType] = Field(min_length=1)
    link_types: list[OntologyLinkType] = Field(default_factory=list)


class OntologyRegistry(RegistryModel):
    registry: RegistryMetadata
    ontology: OntologyDefinition
