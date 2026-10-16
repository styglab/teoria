from typing import Literal

from pydantic import Field, field_validator

from teoria.registry.schema.common import (
    IdentifiedModel,
    RegistryMetadata,
    RegistryModel,
    SNAKE_CASE_PATTERN,
)


class RuleArgumentDefinition(IdentifiedModel):
    description: str
    data_type: str
    required: bool = False


class EligibilityRuleDefinition(IdentifiedModel):
    description: str
    version: str
    evaluator: str
    evaluability: Literal[
        "machine_verifiable",
        "document_verifiable",
        "derived_verifiable",
        "human_judgment_required",
    ]
    arguments: list[RuleArgumentDefinition] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    missing_fact_result: Literal["needs_review"] = "needs_review"

    @field_validator("evaluator")
    @classmethod
    def evaluator_must_be_snake_case(cls, value: str) -> str:
        if not SNAKE_CASE_PATTERN.fullmatch(value):
            raise ValueError("evaluator must be snake_case")
        return value


class EligibilityRuleRegistry(RegistryModel):
    registry: RegistryMetadata
    eligibility_rules: list[EligibilityRuleDefinition]
