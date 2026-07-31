from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContractMetadata(ContractModel):
    version: str
    registered_at: date


class IdentifiedContract(ContractModel):
    id: str
    name: str | None = None

    @field_validator("id")
    @classmethod
    def id_must_be_snake_case(cls, value: str) -> str:
        if not SNAKE_CASE_PATTERN.fullmatch(value):
            raise ValueError("contract id must be snake_case")
        return value


class ValueDefinition(ContractModel):
    value: str
    label: str | None = None


class FieldDefinition(ContractModel):
    """A wire field whose id preserves the provider's original spelling."""

    id: str | None = None
    name: str | None = None
    type: Literal["object", "array"] | None = None
    data_type: str | None = None
    ref: str | None = None
    default: Any = None
    max_items: int | None = Field(default=None, gt=0)
    fields: list[FieldDefinition] = Field(default_factory=list)
    items: FieldDefinition | None = None
    values: list[ValueDefinition] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> "FieldDefinition":
        declared_shapes = sum(value is not None for value in (self.type, self.data_type, self.ref))
        if declared_shapes != 1:
            raise ValueError("field must declare exactly one of type, data_type, or ref")
        if self.ref and self.fields:
            raise ValueError("ref cannot be combined with fields")
        if self.type == "array" and self.items is None:
            raise ValueError("array field must declare items")
        if self.type != "array" and self.items is not None:
            raise ValueError("items is only valid for an array field")
        if self.type != "array" and self.max_items is not None:
            raise ValueError("max_items is only valid for an array field")
        if self.type != "object" and self.fields:
            raise ValueError("nested fields are only valid for an object field")
        if self.type == "object" and not self.fields:
            raise ValueError("object field must declare fields")
        if self.required and self.type != "object" and self.ref is None:
            raise ValueError("required is only valid for an object or ref field")
        return self


class Provider(ContractModel):
    organization: str
    distribution: str | None = None


class Specification(ContractModel):
    format: str
    version: str
    schema_version: str | None = None
    api_version: str | None = None
    source_document: str | None = None


class Authentication(ContractModel):
    type: Literal["api_key", "basic", "bearer", "none"]
    location: str | None = Field(default=None, alias="in")
    name: str | None = None
    credential_env: str | None = None

    @model_validator(mode="after")
    def validate_api_key(self) -> "Authentication":
        if self.type == "api_key":
            if self.location not in {"query", "header"}:
                raise ValueError("api_key authentication requires in: query or header")
            if not self.name:
                raise ValueError("api_key authentication requires name")
            if not self.credential_env:
                raise ValueError("api_key authentication requires credential_env")
        return self

    @field_validator("credential_env")
    @classmethod
    def credential_env_must_be_a_variable_name(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("credential_env must be an environment variable name")
        return value


class Access(ContractModel):
    base_url: str
    authentication: Authentication | None = None

    @field_validator("base_url")
    @classmethod
    def base_url_must_be_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        return value.rstrip("/")


class ObjectDefinition(IdentifiedContract):
    fields: list[FieldDefinition]


class Components(ContractModel):
    objects: list[ObjectDefinition] = Field(min_length=1)


class FieldContainer(ContractModel):
    type: Literal["object"] | None = None
    fields: list[FieldDefinition] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)


class Request(ContractModel):
    content_type: str | None = None
    query: FieldContainer | None = None
    header: FieldContainer | None = None
    body: FieldContainer | None = None


class ResponseData(ContractModel):
    record_path: str
    ref: str | None = None
    fields: list[FieldDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_one_schema(self) -> "ResponseData":
        if bool(self.ref) == bool(self.fields):
            raise ValueError("response data must declare exactly one of ref or fields")
        return self


class SuccessCondition(ContractModel):
    field: str
    equals: str


class ResponseControl(FieldContainer):
    record_path: str
    success: SuccessCondition


class Response(ContractModel):
    content_type: str
    http_status: int = Field(ge=100, le=599)
    control: ResponseControl | None = None
    data: ResponseData


class PaginationField(ContractModel):
    request: str


class Pagination(ContractModel):
    type: Literal["page_number"]
    page: PaginationField
    page_size: PaginationField
    total_count: str


class ErrorDefinition(ContractModel):
    http_status: int = Field(ge=100, le=599)
    source_code: str | None = None
    message: str


class Operation(IdentifiedContract):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str
    description: str | None = None
    idempotent: bool = False
    request: Request | None = None
    response: Response
    pagination: Pagination | None = None
    errors: list[ErrorDefinition] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def path_must_be_absolute(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("operation path must start with '/'")
        return value

    @model_validator(mode="after")
    def get_must_not_have_body(self) -> "Operation":
        if self.method in {"GET", "HEAD"} and self.request and self.request.body:
            raise ValueError(f"{self.method} operation cannot declare a request body")
        return self


class ProviderDefinition(IdentifiedContract):
    provider: Provider
    type: Literal["api"]
    specification: Specification
    access: Access
    components: Components
    operations: list[Operation] = Field(min_length=1)


class ProviderRegistry(ContractModel):
    registry: ContractMetadata
    connector: ProviderDefinition
