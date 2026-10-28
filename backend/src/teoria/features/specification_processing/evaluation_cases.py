"""Frozen source cases and seeded, notice/template-grouped evaluation sampling."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
import re
import unicodedata
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import Field, model_validator
from teoria.features.specification_processing.models import Record, SourceDocument


class ClassificationEvidence(Record):
    path: Path
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    code_pointer: str
    notice_pointer: str


class EntityCase(Record):
    name: str = Field(min_length=1)
    source_text: str = Field(min_length=1, max_length=1000)
    kind: str | None = None
    evidence_mode: Literal['existence','mention'] = 'existence'
    owner: str | None = None


class RelationCase(Record):
    source: str
    target: str
    kind: str
    source_text: str = Field(min_length=1, max_length=1000)
    source_owner: str | None = None
    target_owner: str | None = None


class RequirementCase(Record):
    subjects: list[str] = Field(min_length=1)
    value_raw: str = Field(min_length=1)
    unit_raw: str | None = None
    operator: str
    qualifiers_raw: list[str] | None = None
    qualifier_mode: Literal['required_subset','exact'] = 'required_subset'
    forbidden_qualifiers: list[str] = Field(default_factory=list)
    property_keys: list[str] = Field(default_factory=list)
    role: str | None = None
    scope: str | None = None
    owner: str | None = None
    source_text: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def explicit_exact_qualifiers(self):
        if self.qualifier_mode=='exact' and self.qualifiers_raw is None:
            raise ValueError('exact qualifier checks require an explicit list, including [] for none')
        return self


class EvaluationDocument(SourceDocument):
    notice_number: str | None = Field(default=None,min_length=1)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    classification_code: str | None = Field(default=None,pattern=r'^\d{10}$')
    classification_evidence: ClassificationEvidence | None = None
    template_family: str | None = None
    layout: Literal['table', 'prose', 'mixed', 'unknown'] = 'unknown'
    label_status: Literal['silver', 'human_reviewed'] = 'silver'
    entity_aliases: dict[str,list[str]] = Field(default_factory=dict)
    entities: list[EntityCase] = Field(default_factory=list)
    relations: list[RelationCase] = Field(default_factory=list)
    requirements: list[RequirementCase] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_cases(self):
        present=[self.notice_number is not None,self.classification_code is not None,self.classification_evidence is not None]
        if any(present) and not all(present):
            raise ValueError('classification requires complete notice and metadata evidence')
        aliases={}
        norm=lambda value:re.sub(r'\s+','',unicodedata.normalize('NFKC',value))
        for name,values in self.entity_aliases.items():
            canonical=norm(name)
            for value in [name,*values]:
                key=norm(value)
                if not key or key in aliases and aliases[key]!=canonical:
                    raise ValueError('empty or ambiguous entity alias')
                aliases[key]=canonical
        for cases in (self.entities,self.relations,self.requirements):
            keys=[json.dumps(c.model_dump(),sort_keys=True,ensure_ascii=False) for c in cases]
            if len(keys)!=len(set(keys)):raise ValueError('duplicate frozen evaluation cases')
        return self


class EvaluationManifest(Record):
    cycle_id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,59}$')
    classification_code: str | None = Field(default='4321150102', pattern=r'^\d{10}$')
    selection_mode: Literal['classified_random','fixed_sources'] = 'classified_random'
    case_contract_version: Literal[2] = 2
    purpose: Literal['extraction_improvement','grader_calibration'] = 'extraction_improvement'
    replay_of: str | None = None
    documents: list[EvaluationDocument] = Field(min_length=1, max_length=1000)
    regression_documents: list[EvaluationDocument] = Field(default_factory=list, max_length=100)
    sample_size: int = Field(default=10, ge=2, le=100)
    seed: int | None = None
    history_reviewed: bool = False
    excluded_notices: list[str] = Field(default_factory=list)
    excluded_sha256: list[str] = Field(default_factory=list)
    parser_python: str | None = None
    model: str | None = None
    concurrency: int = Field(default=2, ge=1, le=4)
    model_concurrency: int = Field(default=4, ge=1, le=4)
    model_timeout_seconds: int = Field(default=180, ge=1, le=600)
    run_timeout_seconds: int = Field(default=1800, ge=1, le=14400)

    @model_validator(mode='after')
    def unique_ids(self):
        all_documents=self.documents+self.regression_documents
        if self.selection_mode=='classified_random':
            if self.classification_code is None or any(d.classification_evidence is None for d in all_documents):
                raise ValueError('classified sampling requires classification metadata for every document')
        elif self.classification_code is not None or any(d.classification_code is not None for d in all_documents):
            raise ValueError('fixed source checks require explicitly absent classification')
        ids=[d.document_id for d in all_documents]
        if len(ids)!=len(set(ids)):raise ValueError('evaluation document IDs must be unique')
        if (self.purpose=='grader_calibration')!=(self.replay_of is not None):
            raise ValueError('grader calibration requires an explicit prior-cycle replay')
        return self


def file_sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):digest.update(chunk)
    return digest.hexdigest()


def local_source(document: SourceDocument) -> Path:
    parsed=urlsplit(document.source_uri)
    if parsed.scheme not in {'', 'file'} or parsed.netloc not in {'', 'localhost'}:
        raise ValueError('evaluation requires already available local originals')
    return Path(unquote(parsed.path)).resolve(strict=True)


def pointer(value, path):
    if not path.startswith('/'):raise ValueError('evidence requires an absolute JSON pointer')
    for key in path[1:].split('/'):
        key=key.replace('~1','/').replace('~0','~')
        if isinstance(value,list):
            if not key.isdigit() or len(key)>1 and key.startswith('0'):raise ValueError('invalid JSON array pointer')
            value=value[int(key)]
        else:value=value[key]
    return value


def verify_document(document: EvaluationDocument, *, allow_unclassified=False):
    source=local_source(document)
    if source.stat().st_size>25*1024*1024:raise ValueError('source exceeds 25 MiB')
    if file_sha256(source)!=document.sha256:raise ValueError('evaluation source checksum mismatch')
    evidence=document.classification_evidence
    if evidence is None:
        if not allow_unclassified:
            raise ValueError('classification metadata is required')
        return
    if file_sha256(evidence.path)!=evidence.sha256:raise ValueError('classification evidence checksum mismatch')
    record=json.loads(evidence.path.read_text())
    if str(pointer(record,evidence.code_pointer))!=document.classification_code:
        raise ValueError('classification is not supported by source metadata')
    if str(pointer(record,evidence.notice_pointer))!=document.notice_number:
        raise ValueError('classification evidence belongs to another notice')


def sample_documents(manifest: EvaluationManifest, history: dict, seed: int):
    """Union related notices/templates/bytes before excluding or assigning whole groups."""
    if manifest.selection_mode=='fixed_sources':
        docs=sorted(manifest.documents,key=lambda d:d.document_id)
        all_docs=docs+manifest.regression_documents
        if len({d.sha256 for d in all_docs})!=len(all_docs):
            raise ValueError('fixed source checks require distinct original bytes')
        if len(all_docs)>100:
            raise ValueError('fixed source checks exceed 100 documents')
        return ({'development':[d.document_id for d in docs],'validation':[],
                 'regression':[d.document_id for d in manifest.regression_documents]},all_docs,
                {'sampled_documents':0,'fixed_documents':len(all_docs),'independent_groups':None,
                 'freshness':'known_fixed_sources','selection_mode':'fixed_sources'})
    docs=sorted((d for d in manifest.documents if d.classification_code==manifest.classification_code),key=lambda d:d.document_id)
    parent=list(range(len(docs)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(a,b):parent[find(b)]=find(a)
    keys={}
    for i,d in enumerate(docs):
        for key in [('notice',d.notice_number),('hash',d.sha256),*([('template',d.template_family)] if d.template_family else [])]:
            if key in keys:union(i,keys[key])
            else:keys[key]=i
    groups=defaultdict(list)
    for i,d in enumerate(docs):groups[find(i)].append(d)
    used=history.get('used',[])
    seen_notices={d['notice_number'] for d in used}|set(manifest.excluded_notices)
    seen_hashes={d['sha256'] for d in used}|set(manifest.excluded_sha256)
    seen_templates={d.get('template_family') for d in used if d.get('template_family')}
    for document in manifest.regression_documents:
        if document.classification_code!=manifest.classification_code:raise ValueError('regression classification mismatch')
        seen_notices.add(document.notice_number);seen_hashes.add(document.sha256)
        if document.template_family:seen_templates.add(document.template_family)
    eligible=[]
    for group in groups.values():
        if any(d.notice_number in seen_notices or d.sha256 in seen_hashes or d.template_family and d.template_family in seen_templates for d in group):continue
        # Identical bytes appear once, but every alias remains in the use history.
        unique={}
        for d in group:unique.setdefault(d.sha256,d)
        eligible.append((list(unique.values()),group))
    buckets=defaultdict(list)
    for group,aliases in eligible:
        bucket=tuple(sorted({(Path(d.filename).suffix.lower(),d.layout) for d in group}))
        buckets[bucket].append((group,aliases))
    rng=random.Random(seed)
    for bucket in buckets.values():rng.shuffle(bucket)
    selected=[];count=0
    while buckets and count<manifest.sample_size:
        order=sorted(buckets);rng.shuffle(order)
        for key in order:
            group,aliases=buckets[key].pop();selected.append((group,aliases));count+=len(group)
            if not buckets[key]:del buckets[key]
            if count>=manifest.sample_size:break
    rng.shuffle(selected)
    splits={'development':[], 'validation':[], 'regression':[]};aliases=[]
    for group,all_aliases in selected:
        side='development' if len(splits['development'])<=len(splits['validation']) else 'validation'
        splits[side].extend(d.document_id for d in group);aliases.extend(all_aliases)
    sampled_hashes={d.sha256 for d in aliases};sampled_notices={d.notice_number for d in aliases}
    sampled_templates={d.template_family for d in aliases if d.template_family}
    for d in manifest.regression_documents:
        if d.classification_code!=manifest.classification_code:raise ValueError('regression classification mismatch')
        if d.sha256 in sampled_hashes or d.notice_number in sampled_notices or d.template_family and d.template_family in sampled_templates:
            raise ValueError('regression and fresh documents overlap')
        splits['regression'].append(d.document_id)
    if sum(map(len,splits.values()))>100:raise ValueError('whole-group sample exceeds 100 documents')
    return splits,aliases,{'eligible_groups':len(eligible),'sampled_documents':count,
        'independent_groups':len(selected),'freshness':'history_checked' if manifest.history_reviewed else 'unknown_prior_exposure'}
