"""Portable, checksummed observations for goods normalization authoring."""
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .models import OntologyReference, Record, checksum


class CandidateContext(Record):
    kind: Literal['entity', 'requirement', 'relation']
    label: str = Field(min_length=1)
    source_kind: str
    target_concept_ids: list[UUID] = Field(default_factory=list)
    unresolved_targets: list[str] = Field(default_factory=list)
    source_concept_id: UUID | None = None
    destination_concept_id: UUID | None = None
    role: str = 'unknown'
    scope: str = 'unknown'
    value_type: str = 'unknown'
    unit: str | None = None


class CandidateObservation(Record):
    document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    local_id: str = Field(min_length=1)
    evidence: list[dict] = Field(default_factory=list)
    source_text: str
    grounded: bool
    raw: dict


class CandidateGroup(Record):
    group_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    context: CandidateContext
    aliases: list[str] = Field(min_length=1)
    observations: list[CandidateObservation] = Field(min_length=1)

    @model_validator(mode='after')
    def verify_identity(self):
        if self.group_id != checksum(self.context):
            raise ValueError('candidate group context checksum mismatch')
        return self


class CandidateBundle(Record):
    schema_version: Literal[1] = 1
    artifact_kind: Literal['goods_meaning_candidates'] = 'goods_meaning_candidates'
    classification_code: str = Field(pattern=r'^\d{10}$')
    ontology: OntologyReference
    groups: list[CandidateGroup] = Field(max_length=5000)
    checksum: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def verify_integrity(self):
        if self.checksum != checksum(self.model_dump(mode='json', exclude={'checksum'})):
            raise ValueError('candidate bundle checksum mismatch')
        if len({g.group_id for g in self.groups}) != len(self.groups):
            raise ValueError('duplicate candidate groups')
        seen = set()
        for group in self.groups:
            for observation in group.observations:
                key = (group.context.kind, observation.source_sha256, observation.local_id)
                if key in seen:
                    raise ValueError('duplicate candidate observation')
                seen.add(key)
        return self
