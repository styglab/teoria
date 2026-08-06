from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from teoria.registry.schema.common import IdentifiedModel, RegistryMetadata, RegistryModel, SNAKE_CASE_PATTERN


REFERENCE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


class CapabilityInput(RegistryModel):
    property: str | None = None
    data_type: str | None = None
    field: str | None = None
    operator: Literal["eq", "gte", "lte"] = "eq"
    fields: dict[str, "CapabilityInput"] = Field(default_factory=dict)
    collection: Literal["scalar", "list"] = "scalar"
    required: bool = False
    default: Any = None

    @model_validator(mode="after")
    def validate_input_shape(self) -> "CapabilityInput":
        declared_shapes = sum((self.property is not None, self.data_type is not None, bool(self.fields)))
        if declared_shapes != 1:
            raise ValueError("input must declare exactly one of property, data_type, or fields")
        if self.field and self.data_type is None:
            raise ValueError("direct field binding is only valid for a data_type input")
        if self.operator != "eq" and not (self.field or self.property):
            raise ValueError("non-equality operator requires a field or property binding")
        if self.required and self.default is not None:
            raise ValueError("required input cannot declare a default")
        for field_id in self.fields:
            if not SNAKE_CASE_PATTERN.fullmatch(field_id):
                raise ValueError(f"input field id '{field_id}' must be snake_case")
        return self


class CapabilityStep(RegistryModel):
    id: str | None = None
    call: str

    @field_validator("id")
    @classmethod
    def id_must_be_snake_case(cls, value: str | None) -> str | None:
        if value is not None and not SNAKE_CASE_PATTERN.fullmatch(value):
            raise ValueError("step id must be snake_case")
        return value

    @field_validator("call")
    @classmethod
    def call_must_reference_operation(cls, value: str) -> str:
        if not REFERENCE_PATTERN.fullmatch(value) or len(value.split(".")) != 2:
            raise ValueError("call must use '<source>.<operation>'")
        return value


class CapabilityOutcome(RegistryModel):
    type: Literal["exact_match_presence", "active_period_presence"]
    input: str
    response_field: str | None = None
    period_field: str | None = None
    matched_status: str
    unmatched_status: str

    @field_validator("input", "matched_status", "unmatched_status")
    @classmethod
    def values_must_be_snake_case(cls, value: str) -> str:
        if not SNAKE_CASE_PATTERN.fullmatch(value):
            raise ValueError("outcome values must be snake_case")
        return value

    @field_validator("response_field", "period_field")
    @classmethod
    def response_field_must_be_a_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split(".")
        if len(parts) != 4 or parts[2] != "response" or not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("response_field must use '<source>.<operation>.response.<field>'")
        return value

    @model_validator(mode="after")
    def validate_field_for_type(self) -> "CapabilityOutcome":
        if self.type == "exact_match_presence" and not self.response_field:
            raise ValueError("exact_match_presence requires response_field")
        if self.type == "active_period_presence" and not self.period_field:
            raise ValueError("active_period_presence requires period_field")
        return self


class CapabilityDefinition(IdentifiedModel):
    description: str
    inputs: dict[str, CapabilityInput] = Field(default_factory=dict)
    steps: list[CapabilityStep] = Field(min_length=1)
    returns: list[str] = Field(min_length=1)
    outcome: CapabilityOutcome | None = None

    @model_validator(mode="after")
    def validate_local_references(self) -> "CapabilityDefinition":
        for input_id in self.inputs:
            if not SNAKE_CASE_PATTERN.fullmatch(input_id):
                raise ValueError(f"input id '{input_id}' must be snake_case")
        step_ids = [step.id for step in self.steps if step.id]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step ids must be unique")
        calls = [step.call for step in self.steps]
        if len(calls) != len(set(calls)):
            raise ValueError("step calls must be unique")
        if len(self.returns) != len(set(self.returns)):
            raise ValueError("returns must be unique")
        if self.outcome and self.outcome.input not in self.inputs:
            raise ValueError(f"outcome input '{self.outcome.input}' is not declared")
        return self


class CapabilityRegistry(RegistryModel):
    registry: RegistryMetadata
    capability: CapabilityDefinition
