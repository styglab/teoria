"""Operator inputs for bounded document selection and dictionary management."""
from datetime import date
from typing import Literal
from pydantic import Field, field_validator, model_validator
from teoria.features.specification_processing.models import Record, SourceDocument, StandardReference


class DocumentSelection(Record):
    strategy: Literal['latest'] = 'latest'
    date_from: date | None = None
    date_to: date | None = None
    lookback_days: int = Field(default=365, ge=1, le=3650)
    max_notices_to_scan: int = Field(default=300, ge=1, le=3000)

    @model_validator(mode='after')
    def ordered_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError('date_from must not follow date_to')
        return self


class DictionaryManagement(Record):
    purpose: Literal['dictionary_management','quality_evaluation'] = 'dictionary_management'
    auto_apply: bool = True
    force_review: bool = False
    baseline_dictionary: StandardReference | None = None
    holdout_documents: int = Field(default=5, ge=1, le=30)
    minimum_development_documents: int = Field(default=5, ge=1, le=99)
    max_held_source_ids: int = Field(default=0,ge=0,le=5000)

    @field_validator('purpose',mode='before')
    @classmethod
    def normalize_legacy_purpose(cls,value):
        if value in ('initial_dictionary','incremental_update'):
            return 'dictionary_management'
        return value

    @model_validator(mode='after')
    def pinned_baseline(self):
        if self.purpose == 'quality_evaluation' and not self.baseline_dictionary:
            raise ValueError('quality evaluation requires a baseline dictionary')
        if self.purpose == 'quality_evaluation' and self.force_review:
            raise ValueError('force_review is only available for dictionary management')
        return self


class ManagementExecution(Record):
    run_id: str | None = Field(default=None, pattern=r'^[a-z][a-z0-9_]{0,73}$')
    artifact_root: str | None = None
    model: str | None = None  # None uses the worker's configured Codex model.
    concurrency: int = Field(default=2, ge=1, le=4)
    model_concurrency: int = Field(default=4, ge=1, le=4)
    model_timeout_seconds: int = Field(default=180, ge=1, le=600)

    @model_validator(mode='after')
    def artifact_location(self):
        if self.artifact_root:
            from urllib.parse import urlsplit
            SourceDocument.safe_uri(self.artifact_root)
            parsed=urlsplit(self.artifact_root)
            if parsed.scheme not in {'file','s3'} or parsed.query:
                raise ValueError('artifact_root must be file:// or s3://')
        return self


class StandardManagementParameters(Record):
    classification_code: str = Field(pattern=r'^\d{10}$', description='대상 세부품명 10자리 코드')
    target_specifications: int = Field(default=30, ge=1, le=100, description='공고 수가 아닌 확보할 규격서 파일 수')
    selection: DocumentSelection = Field(default_factory=DocumentSelection)
    management: DictionaryManagement = Field(default_factory=DictionaryManagement)
    execution: ManagementExecution = Field(default_factory=ManagementExecution)
    documents: list[SourceDocument] | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_documents(self):
        if self.documents and len({d.document_id for d in self.documents}) != len(self.documents):
            raise ValueError('duplicate document_id')
        return self
