"""Typed input, storage references and execution results for specification processing."""
from __future__ import annotations
import hashlib
import json
from typing import Literal
from uuid import UUID
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from teoria.features.specification_processing.processing_quality import AutomaticApprovalLimits
from teoria.features.semantic_modeling.ontology.publication_contracts import OntologyPublicationRef

class Record(BaseModel):
    model_config = ConfigDict(extra="forbid",hide_input_in_errors=True)

class SourceDocument(Record):
    document_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    notice_number: str | None = None
    source_uri: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    sha256: str | None = Field(default=None,pattern=r"^[a-f0-9]{64}$")

    @field_validator("filename")
    @classmethod
    def safe_filename(cls,value):
        from pathlib import PurePath
        if PurePath(value).name!=value or "\\" in value or value in {'.','..'}:
            raise ValueError("filename must be one leaf name")
        if PurePath(value).suffix.lower() not in {'.hwp','.hwpx','.pdf','.docx','.xlsx','.pptx'}:
            raise ValueError("unsupported specification document format")
        return value

    @field_validator("source_uri")
    @classmethod
    def safe_uri(cls,value):
        parsed=urlsplit(value)
        if parsed.scheme not in {'','file','https','s3'} or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("source must be a file, HTTPS or S3 URI without embedded credentials")
        from urllib.parse import parse_qsl
        if any(k.lower() in {'token','api_key','servicekey','x-amz-signature'} for k,_ in parse_qsl(parsed.query)):
            raise ValueError("authentication must not be embedded in source URI")
        return value

class ArtifactRef(Record):
    key: str
    uri: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = 'application/json'

class StandardReference(Record):
    uri: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator('uri')
    @classmethod
    def safe_reference(cls,value):
        return SourceDocument.safe_uri(value)

class OntologyAlignmentInput(Record):
    """Optional comparison against a bounded, pinned published concept catalogue."""
    snapshot: StandardReference | None = None
    publications: list[OntologyPublicationRef] = Field(default_factory=list, max_length=8)
    concept_ids: list[UUID] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def distinct_concepts(self):
        if (self.snapshot is None) == (not self.publications):
            raise ValueError('provide either publication references or one pinned context snapshot')
        versions = [ref.version_id for ref in self.publications]
        if len(versions) != len(set(versions)):
            raise ValueError('duplicate ontology publication')
        if len(set(self.concept_ids)) != len(self.concept_ids):
            raise ValueError('duplicate ontology context concept')
        return self

class SpecificationRun(Record):
    run_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    mode: Literal['standard_management','document_processing']
    application_release_id: UUID | None = None
    classification_code: str | None = Field(default=None,pattern=r"^\d{10}$")
    use_expression_dictionary: bool = True
    dictionary_auto_approve: bool = True
    dictionary_rebuild_from_sources: bool = False
    dictionary_meaning_auto_approve: bool = True
    auto_apply_source_literals: bool = True
    auto_approve_application_standard: bool = False
    automatic_approval_limits: AutomaticApprovalLimits = Field(default_factory=AutomaticApprovalLimits)
    ontology_alignment: OntologyAlignmentInput | None = None
    dictionary_standard: StandardReference | None = None
    dictionary_baseline: StandardReference | None = None
    dictionary_require_validation: bool = Field(default=True,
        description='Legacy input retained; automatic dictionary changes always require separate validation documents')
    dictionary_max_held_source_ids: int | None = Field(default=None,ge=0)
    dictionary_reconcile: bool = False
    dictionary_evidence_corpus: list[StandardReference] = Field(default_factory=list,max_length=1000)
    dictionary_corpus: list[StandardReference] = Field(default_factory=list,max_length=1000)
    dictionary_validation_corpus: list[StandardReference] = Field(default_factory=list,max_length=1000)
    documents: list[SourceDocument] = Field(min_length=1,max_length=100)
    artifact_root: str = Field(min_length=1)
    standard: StandardReference | None = None
    extraction_checkpoint: StandardReference | None = None
    reuse_stage_checkpoints: bool = True
    parser_python: str | None = None
    model: str | None = None
    concurrency: int = Field(default=2,ge=1,le=4)
    model_concurrency: int = Field(default=4,ge=1,le=4)
    model_timeout_seconds: int = Field(default=180,ge=1,le=600)

    @model_validator(mode='after')
    def check_contract(self):
        if not self.use_expression_dictionary and (
            self.dictionary_standard or self.dictionary_baseline or self.dictionary_rebuild_from_sources
            or self.dictionary_reconcile or self.dictionary_corpus or self.dictionary_evidence_corpus
            or self.dictionary_validation_corpus or self.application_release_id
            or self.auto_approve_application_standard
        ):
            raise ValueError('dictionary inputs and application-standard approval require expression dictionary')
        if self.auto_approve_application_standard and self.mode != 'standard_management':
            raise ValueError('automatic processing-standard approval requires standard_management')
        if self.application_release_id and (self.mode != 'document_processing' or self.dictionary_standard is None
                or self.dictionary_auto_approve or self.dictionary_meaning_auto_approve):
            raise ValueError('application release requires fixed standard and dictionary without automatic approvals')
        if self.dictionary_rebuild_from_sources and (self.mode!='standard_management' or
                self.dictionary_auto_approve or self.dictionary_meaning_auto_approve or self.dictionary_standard
                or self.dictionary_baseline or self.dictionary_validation_corpus or self.dictionary_evidence_corpus
                or self.dictionary_corpus):
            raise ValueError('source rebuild requires standard_management, both approvals disabled and no prior dictionary or corpus inputs')
        if len({d.document_id for d in self.documents})!=len(self.documents):
            raise ValueError('duplicate document_id')
        if self.mode=='document_processing' and self.standard is None:
            raise ValueError('document processing requires a pinned standard URI and checksum')
        if self.dictionary_reconcile or self.dictionary_corpus or self.dictionary_validation_corpus or self.dictionary_evidence_corpus:
            if self.mode!='standard_management' or self.dictionary_standard:
                raise ValueError('corpus reconciliation requires standard_management without dictionary_standard')
        if self.dictionary_standard and self.mode=='standard_management':
            raise ValueError('dictionary_standard is read-only; use document_processing')
        SourceDocument.safe_uri(self.artifact_root)
        if urlsplit(self.artifact_root).scheme not in {'file','s3'} or urlsplit(self.artifact_root).query:
            raise ValueError('artifact_root must use file:// or s3://')
        return self

    def input_fingerprint(self):
        return hashlib.sha256(json.dumps(self.model_dump(mode='json'),sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class RunResult(Record):
    run_id: str
    status: Literal['completed','partial','failed']
    artifacts: list[ArtifactRef]
    document_results: list[dict]
    standard: StandardReference | None = None
    summary: dict


class StandardWorkflow(Record):
    workflow_id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,79}$')
    extraction: SpecificationRun
    base_profile_revision_id: UUID
    auto_approve: bool = False

    @model_validator(mode='after')
    def explicit_standard_workflow(self):
        if self.extraction.mode!='standard_management' or self.extraction.standard is not None:
            raise ValueError('workflow extraction must use standard_management without a separately selected standard')
        if not self.extraction.model:raise ValueError('pin the Codex model for standard authoring')
        return self

class PropertyBinding(Record):
    property_id: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    rule_kind: Literal['source_literal','server_literal','typed_definition','source_constraint']
    candidate: dict | None = None
    allowed_values: list[str] | None = None

    @model_validator(mode='after')
    def require_candidate_contract(self):
        if self.rule_kind in {'typed_definition','source_constraint'} and self.candidate is None:
            raise ValueError('semantic adoption rules require their candidate contract')
        return self

class ContextBinding(Record):
    target_types: list[str]
    property_key: str
    unit_context: str
    data_type: str
    role: str
    semantic_scope: str = 'unknown'
    properties: list[PropertyBinding] = Field(min_length=1)

class StandardArtifact(Record):
    schema_version: Literal[1] = 1
    rule_set: Literal['source_only','server'] = 'source_only'
    version: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    classification_code: str | None = Field(default=None,pattern=r'^\d{10}$')
    status: Literal['pipeline_selected_draft'] = 'pipeline_selected_draft'
    published: Literal[False] = False
    definitions: list[dict]
    bindings: list[ContextBinding]
    source_standard_sha256: str | None = None
    parent_standard_sha256: str | None = None

    @model_validator(mode='after')
    def valid_bindings(self):
        ids=[d.get('id') for d in self.definitions]
        if len(ids)!=len(set(ids)) or any(not isinstance(i,str) for i in ids):
            raise ValueError('invalid or duplicate definition ID')
        if self.rule_set=='server':
            from teoria.features.specification_processing.normalization.server_rules import META,validate_classification
            validate_classification(self.classification_code)
            if any(p.rule_kind=='server_literal' and p.property_id not in META for b in self.bindings for p in b.properties):
                raise ValueError('unknown server literal property')
        elif any(p.rule_kind!='source_literal' for b in self.bindings for p in b.properties):
            raise ValueError('domain rules require an explicitly selected server rule set')
        known=set(ids)
        if any(p.property_id not in known for b in self.bindings for p in b.properties):
            raise ValueError('context binding references an unknown definition')
        return self
