from pydantic import Field, field_validator, model_validator

from teoria_provider.schema import ContractModel, IdentifiedContract, SNAKE_CASE_PATTERN


class PipelineCursor(ContractModel):
    field: str
    window_days: int = Field(gt=0)
    overlap_days: int = Field(ge=0)


class PipelineSink(ContractModel):
    source: str
    relations: list[str] = Field(min_length=1)


class PipelineProvenance(ContractModel):
    retain_raw_records: bool = False
    fields: list[str] = Field(default_factory=list)


class PipelineDefinition(IdentifiedContract):
    description: str
    connector: str
    operations: list[str] = Field(min_length=1)
    cursor: PipelineCursor
    sink: PipelineSink
    provenance: PipelineProvenance

    @field_validator("connector", "operations")
    @classmethod
    def identifiers_must_be_snake_case(cls, value):
        values = value if isinstance(value, list) else [value]
        if any(not SNAKE_CASE_PATTERN.fullmatch(item) for item in values):
            raise ValueError("connector and operation ids must be snake_case")
        return value

    @model_validator(mode="after")
    def operations_must_be_unique(self) -> "PipelineDefinition":
        if len(self.operations) != len(set(self.operations)):
            raise ValueError("pipeline operations must be unique")
        if len(self.sink.relations) != len(set(self.sink.relations)):
            raise ValueError("pipeline sink relations must be unique")
        return self


class PipelineRegistry(ContractModel):
    pipeline: PipelineDefinition
