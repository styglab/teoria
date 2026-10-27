"""Approve only grounded source-literal entries; ambiguous meanings remain proposals."""
import re
from collections import Counter
from uuid import UUID

from teoria.features.semantic_modeling.goods_dictionary.contracts import dictionary_checksum as checksum
from teoria.features.semantic_modeling.goods_dictionary.contracts import (
    DictionarySubmission, normalized_source_name, source_literal_definition,
)
from teoria.features.semantic_modeling.goods_dictionary.repository import GoodsDictionaryRepository

POLICY = 'source_literal_v1'


def grounding_error(candidate, sources):
    label = normalized_source_name(candidate.preferred_name)
    if not label:
        return 'empty_source_label'
    named = False
    for evidence in candidate.evidence:
        source = sources.get(evidence.document_id)
        if not source or source.source_sha256 != evidence.source_sha256:
            return 'source_identity_mismatch'
        node = next((n for n in source.nodes if n.locator == evidence.locator), None)
        if node is None or evidence.quote not in node.text:
            return 'quote_not_in_parser_snapshot'
        named = named or label in normalized_source_name(evidence.quote)
    return None if named else 'name_not_in_source'


class GoodsDictionaryService:
    def __init__(self, database_url=None, *, repository=None):
        self.repository = repository or GoodsDictionaryRepository(database_url)

    async def author(self, operation_id, submission: DictionarySubmission, *, actor):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,119}', operation_id):
            raise ValueError('invalid dictionary operation ID')
        digest = checksum(submission)
        sources = {s.document_id:s for s in submission.sources}
        reasons = {c.candidate_key:grounding_error(c,sources) for c in submission.candidates}
        repo = self.repository
        async with repo.transaction() as conn:
            await repo.lock(conn)
            previous = await repo.operation(conn, operation_id)
            if previous:
                if previous['actor'] != actor or previous['request_checksum'] != digest:
                    raise ValueError('dictionary operation identity conflict')
                return previous['result']
            await repo.begin(conn,operation_id,digest,actor)
            decisions = {}
            for candidate in sorted(submission.candidates, key=lambda c:(c.kind!='item_type',c.candidate_key)):
                await repo.event(conn,operation_id,candidate.candidate_key,'proposed','candidate_received',actor,POLICY)
                reason = reasons[candidate.candidate_key]
                owner = None
                if candidate.kind == 'characteristic' and not reason:
                    owner_id = candidate.owner_entry_id
                    if candidate.owner_candidate_key:
                        owner_id = decisions.get(candidate.owner_candidate_key,{}).get('entry_id')
                    if owner_id:
                        try:
                            owner = await repo.by_id(conn,UUID(owner_id))
                        except ValueError:
                            owner = None
                    if not owner or owner['kind']!='item_type' or owner['status']!='approved':
                        reason = 'owner_type_not_approved'
                expected = source_literal_definition(candidate.kind,candidate.preferred_name,owner['preferred_name'] if owner else None)
                if not reason and candidate.definition != expected:
                    reason = 'semantic_definition_requires_review'
                result = {'candidate_key':candidate.candidate_key,'origin_ref':candidate.origin_ref,'status':'held','reason':reason,'entry_id':None}
                if not reason:
                    identity = [candidate.kind,normalized_source_name(candidate.preferred_name),str(owner['entry_id']) if owner else None]
                    stable_key = candidate.kind+'_'+checksum(identity)[:24]
                    body = {'kind':candidate.kind,'stable_key':stable_key,'preferred_name':candidate.preferred_name,
                            'definition':expected,'semantic_maturity':'source_literal','value_kind':candidate.value_kind,
                            'owner_entry_id':str(owner['entry_id']) if owner else None}
                    content_digest = checksum(body)
                    existing = await repo.by_key(conn,stable_key)
                    if existing and existing['content_checksum'] != content_digest:
                        result['reason'] = 'existing_definition_conflict'
                    elif existing:
                        result.update(status='reused',reason='exact_approved_entry',entry_id=str(existing['entry_id']))
                    elif not submission.auto_approve:
                        result.update(status='proposed',reason='automatic_approval_not_requested')
                    else:
                        entry = await repo.insert_entry(conn,body,content_digest,actor,POLICY)
                        result.update(status='approved',reason='grounded_source_literal',entry_id=str(entry['entry_id']))
                await repo.decision(conn,operation_id,candidate,result,checksum([e.model_dump(mode='json') for e in candidate.evidence]),actor,POLICY)
                await repo.event(conn,operation_id,candidate.candidate_key,result['status'],result['reason'],actor,POLICY,result['entry_id'])
                decisions[candidate.candidate_key] = result
            counts = Counter(d['status'] for d in decisions.values())
            result = {'operation_id':operation_id,'policy_version':POLICY,'approval_mode':'automatic_policy',
                      'status':'partial' if counts['held'] else 'completed','input_checksum':digest,
                      'summary':{k:counts[k] for k in ['approved','reused','held','proposed']},
                      'decisions':list(decisions.values())}
            await repo.finish(conn,operation_id,result)
            return result

    async def list_entries(self, *, query='', kind=None, limit=100):
        async with self.repository.transaction() as conn:
            return await self.repository.entries(conn,query,kind,limit)

    async def operation(self, operation_id, *, actor):
        async with self.repository.transaction() as conn:
            row = await self.repository.operation(conn,operation_id)
            if row is None or row['actor'] != actor:
                raise KeyError(operation_id)
            return row['result']

    async def audit(self, entry_id):
        async with self.repository.transaction() as conn:
            return await self.repository.audit(conn,entry_id)
