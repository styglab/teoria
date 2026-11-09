"""Connector, collection and provider-reference contracts for ingestion."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, HttpUrl, field_validator, model_validator

from teoria.integrations.provider_api.schema import (
    SNAKE_CASE_PATTERN,
    ContractMetadata,
    ContractModel,
    IdentifiedContract,
    ProviderDefinition,
)


class ConnectorRegistry(ContractModel):
    """An upstream API contract used by an ingestion pipeline, not by Runtime."""

    registry: ContractMetadata
    connector: ProviderDefinition


class PipelineCursor(ContractModel):
    """Documented collection baseline; Python Flow parameters control execution."""

    field: str
    window_days: int = Field(gt=0)
    overlap_days: int = Field(ge=0)


class PipelineSink(ContractModel):
    type: Literal["runtime_source", "data_database"] = "runtime_source"
    source: str | None = None
    schema_name: str | None = None
    relations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_destination(self) -> "PipelineSink":
        if self.type == "runtime_source":
            if not self.source or self.schema_name is not None:
                raise ValueError(
                    "runtime_source sink requires source and no schema_name"
                )
        elif not self.schema_name or self.source is not None:
            raise ValueError("data_database sink requires schema_name and no source")
        if self.schema_name and not SNAKE_CASE_PATTERN.fullmatch(self.schema_name):
            raise ValueError("sink schema_name must be snake_case")
        return self


class PipelineProvenance(ContractModel):
    """Reviewed provenance policy implemented by the feature's Python code."""

    retain_raw_records: bool = False
    fields: list[str] = Field(default_factory=list)


class PipelineDefinition(IdentifiedContract):
    """Reviewed collection inventory; execution remains in the named Python flows."""

    description: str
    flow_modules: list[str] = Field(min_length=1)
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
        if len(self.flow_modules) != len(set(self.flow_modules)):
            raise ValueError("pipeline flow_modules must be unique")
        if len(self.operations) != len(set(self.operations)):
            raise ValueError("pipeline operations must be unique")
        if len(self.sink.relations) != len(set(self.sink.relations)):
            raise ValueError("pipeline sink relations must be unique")
        return self


class PipelineRegistry(ContractModel):
    pipeline: PipelineDefinition


class ReferenceFile(ContractModel):
    path: str
    format: Literal[
        "pdf", "docx", "xlsx", "csv", "json", "xml", "yaml", "html", "markdown", "text"
    ]

    @field_validator("path")
    @classmethod
    def path_must_be_relative(cls, value: str) -> str:
        if (
            not value
            or value.startswith(("/", "\\"))
            or ".." in value.replace("\\", "/").split("/")
        ):
            raise ValueError("reference file path must be a safe relative path")
        return value


class ProviderReference(ContractModel):
    status: Literal["draft", "active"] = "active"
    target: Literal["source", "connector"] = "connector"
    provider: str
    source: str
    title: str
    retrieved_at: date
    official_url: HttpUrl | None = None
    files: list[ReferenceFile] = Field(min_length=1)
    registry: str

    @field_validator("source")
    @classmethod
    def source_must_be_snake_case(cls, value: str) -> str:
        if not SNAKE_CASE_PATTERN.fullmatch(value):
            raise ValueError("reference source must be snake_case")
        return value

    @field_validator("registry")
    @classmethod
    def registry_path_must_be_relative(cls, value: str) -> str:
        if (
            not value
            or value.startswith(("/", "\\"))
            or ".." in value.replace("\\", "/").split("/")
        ):
            raise ValueError("reference registry must be a safe relative path")
        return value
