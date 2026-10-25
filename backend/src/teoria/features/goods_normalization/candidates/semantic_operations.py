"""Resumable authoring operations, serialized across API workers by session locks."""
from collections import Counter
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from teoria.integrations.application_database.postgres import connect
from teoria.features.semantic_modeling.ontology.authoring import OntologyAuthoringRepository
from teoria.features.goods_normalization.contracts import checksum
from teoria.features.goods_normalization.candidates.semantic_resolution import resolve_meanings
from teoria.features.goods_normalization.candidates.semantic_authoring import create_ontology_draft, materialize_profile


class SemanticOperations:
    def __init__(self, profiles):
        self.profiles = profiles
        self.database_url = profiles.database_url

    @staticmethod
    def public(row):
        state = row['checkpoint']
        return {'operation_id': row['operation_id'], 'status': row['status'],
            'ontology_draft_id': state.get('ontology_draft_id'),
            'profile_revision_id': state.get('profile_revision_id'),
            'decisions': dict(Counter(d['action'] for d in state.get('semantic_report', {}).get('decisions', []))),
            'error_code': row['error_code']}

    async def get(self, operation_id, *, actor):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            row = await (await conn.execute('SELECT * FROM goods.semantic_operations WHERE operation_id=%s', (operation_id,))).fetchone()
        if row is None or row['actor'] != actor:
            raise KeyError(operation_id)
        return self.public(row)

    async def _save(self, operation_id, state, status, error=None):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            row = await (await conn.execute('''UPDATE goods.semantic_operations SET checkpoint=%s,status=%s,
                error_code=%s,updated_at=now() WHERE operation_id=%s RETURNING *''',
                (Jsonb(state), status, error, operation_id))).fetchone()
        return self.public(row)

    async def execute(self, operation_id, payload, *, actor):
        digest = checksum(payload)
        async with connect(self.database_url, row_factory=dict_row) as conn:
            await conn.execute('''INSERT INTO goods.semantic_operations(operation_id,input_checksum,actor,status)
                VALUES (%s,%s,%s,'running') ON CONFLICT DO NOTHING''', (operation_id, digest, actor))
            row = await (await conn.execute('SELECT * FROM goods.semantic_operations WHERE operation_id=%s', (operation_id,))).fetchone()
            if row['input_checksum'] != digest or row['actor'] != actor:
                raise ValueError('operation ID belongs to different inputs or principal')
        # The lock connection owns no authoring transaction/row locks. Each checkpoint commits separately.
        async with connect(self.database_url) as lock:
            acquired = (await (await lock.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))', ('goods_semantic:' + operation_id,))).fetchone())[0]
            if not acquired:
                return {**self.public(row), 'status': 'running'}
            try:
                async with connect(self.database_url, row_factory=dict_row) as conn:
                    row = await (await conn.execute('SELECT * FROM goods.semantic_operations WHERE operation_id=%s', (operation_id,))).fetchone()
                if row['status'] in {'approved', 'held', 'rejected'}:
                    return self.public(row)
                state = row['checkpoint']
                return await self._advance(operation_id, payload, state, actor)
            except BaseException as exc:
                await self._save(operation_id, state if 'state' in locals() else row['checkpoint'], 'failed', type(exc).__name__)
                raise
            finally:
                await lock.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', ('goods_semantic:' + operation_id,))

    async def _advance(self, operation_id, payload, state, actor):
        from teoria.features.goods_normalization.contracts.candidates import CandidateBundle
        bundles = [CandidateBundle.model_validate(b) for b in payload['bundles']]
        base_id = UUID(payload['base_revision_id'])
        profile, ontology = await self.profiles._candidate_context(base_id, allow_deprecated=True)
        automatic = payload.get('auto_approve', False)
        if automatic and not profile.ontology.namespace.startswith('goods_eval_'):
            raise ValueError('automatic approval requires an evaluation ontology')
        await self._save(operation_id, state, 'running')
        if 'semantic_report' not in state:
            state['semantic_report'] = await resolve_meanings(bundles, profile, ontology,
                model=payload['model'], timeout=payload.get('timeout', 300))
            await self._save(operation_id, state, 'running')
        report = state['semantic_report']
        if all(d['action'] == 'hold' for d in report['decisions']):
            return await self._save(operation_id, state, 'held')
        if 'ontology_draft_id' not in state:
            state.update(await create_ontology_draft(self.profiles, base_id, bundles, report,
                version=payload['version'], actor=actor, resume=True))
            await self._save(operation_id, state, 'running')
        published_id = profile.ontology.version_id
        authoring = OntologyAuthoringRepository(self.database_url)
        if state['ontology_draft_id']:
            published_id = UUID(state['ontology_draft_id'])
            detail = await authoring.get_version(published_id)
            if automatic:
                if detail['status'] == 'draft':
                    await authoring.transition(published_id, action='submit', actor=actor)
                    detail = await authoring.get_version(published_id)
                if detail['status'] == 'in_review':
                    await authoring.transition(published_id, action='approve', actor=actor)
                    detail = await authoring.get_version(published_id)
                if detail['status'] == 'approved':
                    await authoring.publish(published_id, actor=actor)
                    detail = await authoring.get_version(published_id)
            if detail['status'] in {'rejected','deprecated'}:
                return await self._save(operation_id, state, 'rejected')
            if detail['status'] != 'published':
                return await self._save(operation_id, state, 'awaiting_approval')
        if 'profile_revision_id' not in state:
            new = await materialize_profile(self.profiles, base_id, bundles, report,
                published_version_id=published_id, version=payload['version'], actor=actor, resume=True)
            state['profile_revision_id'] = new['revision_id']
            await self._save(operation_id, state, 'running')
        revision_id = UUID(state['profile_revision_id'])
        detail = await self.profiles.get(revision_id)
        if automatic:
            if detail['status'] == 'draft':
                await self.profiles.transition(revision_id, action='submit', actor=actor)
                detail = await self.profiles.get(revision_id)
            if detail['status'] == 'in_review':
                await self.profiles.transition(revision_id, action='approve', actor=actor,
                    comment='Explicit automatic approval for isolated evaluation')
                detail = await self.profiles.get(revision_id)
        if detail['status'] in {'rejected', 'deprecated'}:
            return await self._save(operation_id, state, 'rejected')
        if detail['status'] != 'approved':
            return await self._save(operation_id, state, 'awaiting_approval')
        await self.profiles.export(revision_id)
        return await self._save(operation_id, state, 'approved')
