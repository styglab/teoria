"""Authenticated review policy with pinned profile/publication and immutable artifacts."""
from uuid import uuid4

from teoria.domains.goods.normalization.application.meaning_application import (
    ApprovedInterpretation, InterpretationRequest, apply_interpretation,
)
from teoria.domains.goods.normalization.contracts import NormalizationPackage, canonical_bytes, checksum
from teoria.domains.goods.normalization.profiles.compiler import compile_package
from teoria.domains.goods.normalization.profiles.service import profile_result
from teoria.platform.ontology.authoring.publication_contracts import PublishedOntology


class InterpretationService:
    def __init__(self, repository, profiles, ontology_authoring, reader, store_factory):
        self.repository = repository
        self.profiles = profiles
        self.ontology_authoring = ontology_authoring
        self.reader = reader
        self.store_factory = store_factory

    async def _context(self, conn, request):
        row = await self.profiles.repository.get(conn, request.profile_revision_id, lock=True)
        if row['status'] != 'approved':
            raise ValueError('interpretation_requires_approved_profile')
        package = NormalizationPackage.model_validate(row['package'])
        if package.profile_checksum != row['content_checksum']:
            raise ValueError('interpretation_profile_changed')
        ref = package.profile.ontology
        artifact = await self.ontology_authoring.published_artifact(
            ref.version_id, expected_checksum=ref.checksum, connection=conn, lock=True)
        if artifact is None or artifact['status'] != 'published':
            raise ValueError('interpretation_requires_published_ontology')
        publication = PublishedOntology(ontology=ref, content=artifact['content'])
        rebuilt = compile_package(package.profile, publication.content,
            revision_id=package.profile_revision_id, approval_actor=package.approval_actor)
        if rebuilt.checksum != package.checksum:
            raise ValueError('interpretation_package_changed')
        result = await self.reader({**request.result.model_dump(mode='json'), 'size_bytes': 0})
        result = result.get('result', result)
        return package, publication, result

    @staticmethod
    def _approval(row, request, package, *, actor=None):
        body = dict(artifact_kind='goods_approved_interpretation', status='approved',
            revision_id=str(row['revision_id']), approval_actor=actor or row['approved_by'],
            request=request.model_dump(mode='json'), package_checksum=package.checksum,
            ontology=package.profile.ontology.model_dump(mode='json'))
        return ApprovedInterpretation(**body, checksum=checksum(body))

    async def _load(self, conn, row):
        request = InterpretationRequest.model_validate(await self.reader(row['request_ref']))
        if checksum(request) != row['request_checksum'] or request.review_id != row['review_id']:
            raise ValueError('interpretation_request_changed')
        package, publication, result = await self._context(conn, request)
        if (str(package.profile_revision_id) != str(row['profile_revision_id'])
                or str(package.profile.ontology.version_id) != str(row['ontology_version_id'])
                or package.profile.ontology.checksum != row['ontology_checksum']
                or package.checksum != row['package_checksum']):
            raise ValueError('interpretation_context_changed')
        return request, package, publication, result

    async def create(self, request, *, actor):
        request = InterpretationRequest.model_validate(request)
        async with self.repository.transaction() as conn:
            package, publication, result = await self._context(conn, request)
            # Test all selected interpretations against actual evidence/profile before creating a draft.
            provisional = self._approval({'revision_id': uuid4()}, request, package, actor=actor)
            apply_interpretation(provisional, result, package, publication, run_id='validation')
            async with self.store_factory() as store:
                reference = await store.put(
                    f'specification_processing/interpretations/{request.review_id}/{checksum(request)}/request.json',
                    canonical_bytes(request))
            row = await self.repository.insert(conn, request, reference.model_dump(mode='json'), package, actor=actor)
            await self.repository.event(conn, row, 'created', actor)
        return profile_result(row)

    async def get(self, revision_id):
        async with self.repository.transaction() as conn:
            return profile_result(await self.repository.get(conn, revision_id))

    async def review(self, revision_id):
        async with self.repository.transaction() as conn:
            row = await self.repository.get(conn, revision_id)
            request, package, publication, result = await self._load(conn, row)
            from teoria.domains.goods.normalization.application.meaning_application import validate_interpretation
            document = validate_interpretation(request, result, package, publication)
        entity_ids = {e.subject_id for e in request.entities}
        attribute_ids = {p.observation_id for p in request.properties}
        attribute_ids.update(c.quantity_observation_id for c in request.compositions)
        relation_ids = {c.relation_id for c in request.compositions}
        return {'revision_id': str(revision_id), 'status': row['status'], 'authority': 'suggestion',
            'request_checksum': row['request_checksum'], 'request': request.model_dump(mode='json'),
            'semantic_equivalence_confirmed': False,
            'source_observations': {
                'entities': [e for e in document['entities'] if e['id'] in entity_ids],
                'attributes': [a for a in document['attributes'] if a['id'] in attribute_ids],
                'relations': [r for r in document.get('relations', []) if r['id'] in relation_ids]}}

    async def transition(self, revision_id, *, action, expected_status, expected_request_checksum, actor, comment=None):
        transitions = {('draft','submit'): 'in_review', ('in_review','approve'): 'approved',
                       ('in_review','reject'): 'rejected', ('approved','deprecate'): 'deprecated'}
        async with self.repository.transaction() as conn:
            row = await self.repository.get(conn, revision_id, lock=True)
            if row['status'] != expected_status or row['request_checksum'] != expected_request_checksum:
                raise ValueError('interpretation_changed_since_review')
            status = transitions.get((row['status'], action))
            if status is None:
                raise ValueError('invalid_interpretation_transition')
            if action in {'submit', 'approve'}:
                request, package, publication, result = await self._load(conn, row)
                approval = self._approval(row, request, package, actor=actor)
                apply_interpretation(approval, result, package, publication, run_id='validation')
            row = await self.repository.set_status(conn, row, status, actor=actor)
            await self.repository.event(conn, row, action, actor, comment=comment)
        return profile_result(row)

    async def _approved(self, conn, revision_id):
        row = await self.repository.get(conn, revision_id, lock=True)
        if row['status'] != 'approved':
            raise ValueError('interpretation_approval_required')
        request, package, publication, result = await self._load(conn, row)
        return row, self._approval(row, request, package), package, publication, result

    async def export(self, revision_id):
        async with self.repository.transaction() as conn:
            _, approval, package, publication, result = await self._approved(conn, revision_id)
            apply_interpretation(approval, result, package, publication, run_id='validation')
        return approval.model_dump(mode='json')

    async def apply(self, revision_id, *, run_id, actor, expected_request_checksum):
        async with self.repository.transaction() as conn:
            row, approval, package, publication, result = await self._approved(conn, revision_id)
            if row['request_checksum'] != expected_request_checksum:
                raise ValueError('interpretation_changed_since_review')
            applied = apply_interpretation(approval, result, package, publication, run_id=run_id)
            async with self.store_factory() as store:
                reference = await store.put(
                    f'specification_processing/interpretations/{row["review_id"]}/{run_id}/application.json',
                    canonical_bytes(applied))
            artifact = reference.model_dump(mode='json')
            await self.repository.event(conn, row, 'apply', actor, artifact=artifact, event_key=run_id)
        return {'revision_id': str(revision_id), 'artifact': artifact, 'source_observations_unchanged': True}

    async def audit(self, revision_id):
        async with self.repository.transaction() as conn:
            await self.repository.get(conn, revision_id)
            rows = await self.repository.audit(conn, revision_id)
        return [profile_result(row) for row in rows]
