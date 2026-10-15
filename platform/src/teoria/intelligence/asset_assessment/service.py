from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import date
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from teoria.domains.legal_information.search import LawSearchRequest
from teoria.intelligence.asset_assessment.model_client import AssessmentError
from teoria.intelligence.asset_assessment.models import AssessmentOutput, LawQueries
from teoria.intelligence.binding_candidates import rank_binding_candidates


def verify_table(table: dict, target: dict) -> None:
    if (str(table.get('id')) != target['entity_id']
            or table.get('fullyQualifiedName') != target['fully_qualified_name']
            or table.get('version') != target['version']):
        raise AssessmentError('stale_evidence')


def law_search_queries(columns: list[dict], generated: list[str]) -> list[str]:
    """Korean retrieval expansion only; these keywords do not classify a column."""
    text = ' '.join(str(c.get('name', '')) + ' ' + str(c.get('description') or '') for c in columns).lower()
    seeds = []
    for terms, keyword in (
        (('resident', 'rrn', '주민등록'), '주민등록번호'),
        (('representative', 'name', 'email', 'phone', 'address', '성명', '이름', '전화', '주소'), '개인정보'),
        (('health', 'medical', '건강', '질병'), '민감정보'),
    ):
        if any(term in text for term in terms):
            seeds.append(keyword)
    korean = [query for query in generated if re.search('[가-힣]', query)]
    return list(dict.fromkeys(seeds + korean + ['공공데이터']))[:3]


class AssetAssessmentService:
    def __init__(self, repository, metadata, bindings, model, law_reader=None):
        self.repository, self.metadata, self.bindings = repository, metadata, bindings
        self.model, self.law_reader = model, law_reader

    async def process(self, job: dict) -> None:
        try:
            # Work is bounded below the ten-minute lease; no network call can renew ownership.
            async with asyncio.timeout(480):
                if job['model_name'] != self.model.model:
                    raise AssessmentError('assessment_model_changed')
                proposals, findings, partial = await self.analyze(job)
            await run_in_threadpool(self.repository.finish, job, proposals=proposals,
                                    findings=findings, partial=partial)
        except Exception as exc:
            # Exception messages can contain provider payloads; persist only stable codes.
            code = exc.code if isinstance(exc, AssessmentError) else 'assessment_timeout' if isinstance(exc, TimeoutError) else 'assessment_failed'
            await run_in_threadpool(self.repository.finish, job, proposals=[], findings=[], error_code=code)

    async def analyze(self, job: dict):
        target = job['target_ref']
        table = await self.metadata.get_table_by_name(target['fully_qualified_name'])
        verify_table(table, target)
        selected = set(job['column_names'])
        columns = [c for c in table.get('columns', []) if not selected or c['name'] in selected]
        if len(columns) > 30 or selected - {c['name'] for c in columns}:
            raise AssessmentError('assessment_columns_changed')
        # No row values, samples, or entire OpenMetadata documents go to the model or DB.
        context = {'scopes': job['scopes'], 'assessment_date': str(job['assessment_date']),
                   'disclosure_context': job['disclosure_context'], 'table': {
                       'name': table['name'], 'description': str(table.get('description') or '')[:4000],
                       'columns': [{key: c.get(key) for key in ('name', 'dataType', 'description', 'tags')}
                                   for c in columns]}, 'evidence': {}, 'concepts': []}
        evidence = {}
        column_map = {c['name']: c for c in columns}
        table_ref = f"openmetadata://table/{table['fullyQualifiedName']}"
        evidence['table'] = {'evidence_type': 'openmetadata_metadata', 'source_ref': table_ref,
                             'provenance': {'source_version': str(table['version'])}}
        for c in columns:
            evidence[f"column:{c['name']}"] = {
                'evidence_type': 'openmetadata_metadata',
                'source_ref': f"openmetadata://column/{c['fullyQualifiedName']}",
                'provenance': {'source_version': str(table['version'])},
            }
        concepts = {}
        candidates_by_column = {}
        if 'semantic_alignment' in job['scopes']:
            if self.bindings is None:
                raise AssessmentError('ontology_reader_unavailable')
            published = await run_in_threadpool(self.bindings.list_published_property_concepts)
            for c in columns:
                ranked = rank_binding_candidates(c, published, limit=3)
                candidates_by_column[c['name']] = {item.concept_id for item in ranked}
                for item in ranked:
                    concepts[item.concept_id] = next(p for p in published if str(p['concept_id']) == item.concept_id)
            context['concepts'] = list(concepts.values())
            context['candidates_by_column'] = {k: sorted(v) for k, v in candidates_by_column.items()}
            for identifier, concept in concepts.items():
                evidence[f'concept:{identifier}'] = {
                    'evidence_type': 'published_ontology',
                    'source_ref': f'teoria://ontology/concept/{identifier}',
                    'provenance': {'stable_key': concept['stable_key'], 'version': concept['version']},
                }
        partial = False
        diagnostics = []
        if len(json.dumps(context, ensure_ascii=False, default=str)) > 100_000:
            raise AssessmentError('assessment_context_too_large')
        if 'disclosure_assessment' in job['scopes']:
            if self.law_reader is None:
                partial = True
                diagnostics.append({'scope': 'disclosure_assessment', 'summary': '법령 저장소가 설정되지 않아 진단 근거를 확인하지 못했습니다.', 'code': 'law_reader_unavailable'})
            else:
                queries = await self.model.generate(instruction='Generate up to three Korean keyword queries for disclosure risks. No findings yet.',
                                                    context=context, output_type=LawQueries)
                documents = []
                seen_documents = set()
                for query in law_search_queries(columns, queries.queries):
                    result = await run_in_threadpool(self.law_reader.search, LawSearchRequest(
                        query=query, assessment_date=date.fromisoformat(str(job['assessment_date'])), limit=3))
                    if result['unavailable_versions']:
                        partial = True
                        diagnostics.append({'scope': 'disclosure_assessment', 'summary': '평가 기준일에 해당하는 일부 법령 버전이 수집되지 않았습니다.', 'code': 'law_version_unavailable'})
                    for hit in result['items']:
                        identity = (str(hit['snapshot_id']), hit['path'])
                        if identity in seen_documents or len(documents) >= 5:
                            continue
                        document = await run_in_threadpool(self.law_reader.get_document, UUID(str(hit['snapshot_id'])), hit['path'], max_chars=12000)
                        if not document or document['content_truncated']:
                            partial = True
                            continue
                        seen_documents.add(identity)
                        key = f'law:{len(documents) + 1}'
                        documents.append({'evidence_id': key, **document})
                        evidence[key] = {'evidence_type': 'law_snapshot',
                            'source_ref': f"legal_information://snapshot/{hit['snapshot_id']}?path={hit['path']}",
                            'content_hash': hashlib.sha256(document['content'].encode()).hexdigest(),
                            'provenance': {k: str(hit.get(k) or '') for k in
                                ('law_id', 'mst', 'law_name', 'effective_date', 'snapshot_id', 'path')}
                                | {'assessment_date': str(job['assessment_date'])}}
                context['law_documents'] = documents
                if not documents:
                    partial = True
                    diagnostics.append({'scope': 'disclosure_assessment', 'summary': '확인 가능한 법령 근거를 찾지 못했습니다. 추가 법령 검토가 필요합니다.', 'code': 'law_evidence_not_found'})
        context['evidence'] = evidence
        if len(json.dumps(context, ensure_ascii=False, default=str)) > 100_000:
            raise AssessmentError('assessment_context_too_large')
        output = await self.model.generate(
            instruction=('For metadata_enrichment propose only description changes. For semantic_alignment use only '
                         'supplied per-column published concept candidates, with both column and concept evidence IDs. '
                         'For disclosure_assessment return findings only, cite law documents; recommendations are conditional '
                         'drafts, never confirmed compliance. Report uncertainty and unbound gaps as findings. '
                         'evidence_ids must be exact keys of context.evidence (for example law:1), never paths or source_ref values. '
                         'Do not create glossary terms, tags, quality tests or Ontology in this first version.'),
            context=context, output_type=AssessmentOutput)
        proposals, findings, rejected = await self.validate_output(job, table, column_map, concepts, candidates_by_column, evidence, output)
        if 'disclosure_assessment' in job['scopes'] and not any(f.get('scope') == 'disclosure_assessment' for f in findings):
            partial = True
            diagnostics.append({'scope': 'disclosure_assessment', 'summary': '모델이 개방 진단 결과를 반환하지 않았습니다. 추가 검토가 필요합니다.', 'code': 'disclosure_result_missing'})
        # Reject all effects if the source changed during inference.
        verify_table(await self.metadata.get_table_by_name(target['fully_qualified_name']), target)
        return proposals, diagnostics + findings, partial or rejected

    async def validate_output(self, job, table, columns, concepts, candidates_by_column, evidence, output):
        proposals, findings, seen = [], [], set()
        rejected = False
        for change in output.changes:
            key = (change.kind, change.column_name)
            source_id = f'column:{change.column_name}' if change.column_name else 'table'
            required = {source_id}
            concept = concepts.get(change.concept_id)
            scope = 'metadata_enrichment' if change.kind == 'description' else 'semantic_alignment'
            if change.kind == 'binding':
                required.add(f'concept:{change.concept_id}')
            valid = (scope in job['scopes'] and key not in seen
                     and (change.column_name is None or change.column_name in columns)
                     and required.issubset(change.evidence_ids)
                     and set(change.evidence_ids).issubset(evidence))
            if change.kind == 'binding':
                valid = valid and concept is not None and change.concept_id in candidates_by_column.get(change.column_name, set())
            if change.kind == 'description':
                valid = valid and bool(change.description and change.description.strip())
            if not valid:
                rejected = True
                continue
            seen.add(key)
            column = columns.get(change.column_name)
            fqn = column['fullyQualifiedName'] if column else table['fullyQualifiedName']
            current = column.get('description') if column else table.get('description')
            if change.kind == 'description' and change.description.strip() == (current or '').strip():
                continue
            if change.kind == 'binding':
                existing = await run_in_threadpool(self.bindings.get_active_binding,
                    ontology_concept_id=UUID(change.concept_id), target_type='data_asset', target_locator=fqn)
                if existing:
                    continue
            proposed = {'table_id': str(table['id']), 'source_version': str(table['version'])}
            if change.kind == 'description':
                proposed.update(description=change.description.strip(), source_description=current)
                proposed.update({'column_name': column['name'], 'column_fqn': fqn} if column else {'fully_qualified_name': fqn})
            else:
                proposed.update(ontology_concept_id=change.concept_id, ontology_ref_type=concept['concept_kind'],
                    ontology_stable_key=concept['stable_key'], external_entity_id=fqn, entity_type='column',
                    fully_qualified_name=fqn, external_version=str(table['version']), binding_type='represents')
            proposals.append({'target_type': 'openmetadata_column' if column else 'openmetadata_table',
                'target_ref': f"openmetadata://{'column' if column else 'table'}/{fqn}",
                'suggestion_type': change.kind, 'proposed_value': proposed,
                'confidence': min(change.confidence, 0.69), 'risk_level': 'medium',
                'rationale': change.reason + '\n주의: 메타데이터와 기존 개념에 기초한 추정입니다. 원천 업무 문서 대조가 필요합니다.',
                'model_provider': 'configured_gateway', 'model_name': job['model_name'], 'model_version': None,
                'policy_version': 'asset_assessment_v1', 'submitted_by': job['requested_by'],
                'evidence': [evidence[k] for k in change.evidence_ids]})
        for finding in output.findings:
            if (finding.scope not in job['scopes']
                    or finding.column_name is not None and finding.column_name not in columns
                    or not set(finding.evidence_ids).issubset(evidence)):
                rejected = True
                findings.append({'summary': '진단 결과의 범위·대상·근거 식별자가 입력과 일치하지 않아 제외했습니다.',
                                 'code': 'finding_reference_invalid',
                                 'invalid_evidence_count': len(set(finding.evidence_ids) - evidence.keys()),
                                 'unknown_column': finding.column_name is not None and finding.column_name not in columns,
                                 'unknown_scope': finding.scope not in job['scopes']})
                continue
            item = finding.model_dump()
            item['evidence'] = [evidence[k] for k in finding.evidence_ids]
            if finding.scope == 'disclosure_assessment':
                item['legal_applicability_confirmed'] = False
                item['tag_candidates_verified'] = False
                # Approval / legal basis must never be inferred from the model's own confidence.
                item['internal_processing'] = 'review_required'
                if not any(k.startswith('law:') for k in finding.evidence_ids):
                    item['disclosure_recommendation'] = 'review_required'
                    item['protection_recommendation'] = None
                    item['tag_candidates'] = []
                    item['summary'] = '법령 근거가 확인되지 않았습니다. ' + item['summary']
                    rejected = True
            findings.append(item)
        if rejected:
            findings.append({'summary': '일부 모델 결과는 대상·근거·분석 범위 검증을 통과하지 못해 제외했습니다.', 'code': 'invalid_candidates_excluded'})
        return proposals, findings, rejected
