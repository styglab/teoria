"""Authoring transactions and immutable approved packages for goods normalization."""
from uuid import UUID,uuid4
import json
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from teoria.persistence.postgres import connect
from teoria_goods_normalization import NormalizationPackage,NormalizationProfile,checksum
from .compiler import compile_package,resolve_profile_template


class NormalizationProfileRepository:
    def __init__(self,database_url: str):self.database_url=database_url

    async def _candidate_context(self,revision_id,*,allow_deprecated=False):
        async with connect(self.database_url,row_factory=dict_row) as conn:
            row=await self._get(conn,revision_id)
            if row['status']!='approved':raise ValueError('candidate comparison requires an approved base profile')
            profile=NormalizationProfile.model_validate(row['content'])
            if checksum(profile)!=row['content_checksum']:raise ValueError('profile checksum mismatch')
            statuses=['published','deprecated'] if allow_deprecated else ['published']
            snapshot=await (await conn.execute('''SELECT a.content,a.checksum
                FROM ontology.runtime_artifacts a JOIN ontology.ontology_versions v USING (ontology_version_id)
                WHERE a.ontology_version_id=%s AND v.status=ANY(%s) ''',
                (profile.ontology.version_id,statuses))).fetchone()
            if snapshot is None or checksum(snapshot['content'])!=snapshot['checksum']:
                raise ValueError('published ontology artifact unavailable or invalid')
        return profile,snapshot['content']

    async def candidate_proposals(self,base_revision_id,bundles):
        from .candidate_proposals import propose_candidates
        profile,ontology=await self._candidate_context(base_revision_id)
        return propose_candidates(bundles,profile,ontology)

    async def create_from_candidates(self,base_revision_id,bundles,selections,*,version,actor):
        from .candidate_proposals import draft_from_candidates
        profile,ontology=await self._candidate_context(base_revision_id)
        draft,proposal_checksum=draft_from_candidates(bundles,profile,ontology,selections,version=version)
        provenance=json.dumps({'source':'candidate_proposals','base_revision_id':str(base_revision_id),
            'proposal_checksum':proposal_checksum,'input_checksums':sorted({b.checksum for b in bundles}),
            'selections':[s.model_dump(mode='json') for s in selections]},sort_keys=True)
        return await self.create(draft,actor=actor,provenance_comment=provenance)

    async def create_from_template(self,version_id: UUID,template: dict,*,actor: str):
        async with connect(self.database_url,row_factory=dict_row) as conn:
            row=await (await conn.execute('''SELECT a.content,a.checksum FROM ontology.runtime_artifacts a
                JOIN ontology.ontology_versions v USING (ontology_version_id)
                WHERE a.ontology_version_id=%s AND v.status='published' ''',(version_id,))).fetchone()
            if row is None:raise ValueError('template requires a published ontology artifact')
            if checksum(row['content'])!=row['checksum']:raise ValueError('ontology artifact checksum mismatch')
            profile=resolve_profile_template(template,row['content'],version_id=version_id)
        # Approval revalidates the selected immutable version inside its transaction.
        return await self.create(profile,actor=actor)

    async def create(self,profile: NormalizationProfile,*,actor: str,provenance_comment: str|None=None):
        async with connect(self.database_url,row_factory=dict_row) as conn:
            row=await (await conn.execute('''INSERT INTO goods.normalization_profile_revisions
                (revision_id,profile_key,version,ontology_version_id,content,content_checksum,created_by,updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                (uuid4(),profile.profile_key,profile.version,profile.ontology.version_id,
                 Jsonb(profile.model_dump(mode='json')),checksum(profile),actor,actor))).fetchone()
            await self._event(conn,row,'created',actor,provenance_comment)
        return self._result(row)

    async def get(self,revision_id: UUID):
        async with connect(self.database_url,row_factory=dict_row) as conn:
            row=await self._get(conn,revision_id)
        return self._result(row)

    async def update(self,revision_id: UUID,profile: NormalizationProfile,*,actor: str):
        async with connect(self.database_url,row_factory=dict_row) as conn:
            current=await self._get(conn,revision_id,lock=True)
            if current['status']!='draft':raise ValueError('only draft profiles may be edited')
            if (profile.profile_key,profile.version)!=(current['profile_key'],current['version']):
                raise ValueError('profile identity cannot change; create a new revision')
            row=await (await conn.execute('''UPDATE goods.normalization_profile_revisions
                SET ontology_version_id=%s,content=%s,content_checksum=%s,updated_by=%s,updated_at=now()
                WHERE revision_id=%s RETURNING *''',(profile.ontology.version_id,Jsonb(profile.model_dump(mode='json')),
                checksum(profile),actor,revision_id))).fetchone()
            await self._event(conn,row,'updated',actor,None)
        return self._result(row)

    async def transition(self,revision_id: UUID,*,action: str,actor: str,comment: str|None=None):
        transitions={('draft','submit'):'in_review',('in_review','request_changes'):'draft',
                     ('in_review','approve'):'approved',('in_review','reject'):'rejected',('approved','deprecate'):'deprecated'}
        async with connect(self.database_url,row_factory=dict_row) as conn:
            row=await self._get(conn,revision_id,lock=True)
            status=transitions.get((row['status'],action))
            if status is None:raise ValueError('invalid profile transition')
            package=row['package']
            if action in {'submit','approve'}:
                profile=NormalizationProfile.model_validate(row['content'])
                if checksum(profile)!=row['content_checksum']:raise ValueError('profile content checksum mismatch')
                snapshot=await (await conn.execute('''SELECT a.content,a.checksum,v.status
                    FROM ontology.runtime_artifacts a JOIN ontology.ontology_versions v USING (ontology_version_id)
                    WHERE a.ontology_version_id=%s AND a.checksum=%s FOR SHARE OF v''',
                    (profile.ontology.version_id,profile.ontology.checksum))).fetchone()
                if snapshot is None or snapshot['status']!='published':raise ValueError('profile requires a published ontology artifact')
                compiled=compile_package(profile,snapshot['content'],revision_id=revision_id,approval_actor=actor)
                if action=='approve':package=compiled.model_dump(mode='json')
            row=await (await conn.execute('''UPDATE goods.normalization_profile_revisions
                SET status=%s,package=%s,updated_by=%s,updated_at=now() WHERE revision_id=%s RETURNING *''',
                (status,Jsonb(package) if package is not None else None,actor,revision_id))).fetchone()
            await self._event(conn,row,action,actor,comment)
        return self._result(row)

    async def export(self,revision_id: UUID) -> NormalizationPackage:
        async with connect(self.database_url,row_factory=dict_row) as conn:
            row=await self._get(conn,revision_id)
        if row['status']!='approved':raise ValueError('only approved profiles can be exported')
        package=NormalizationPackage.model_validate(row['package'])
        if package.profile_checksum!=row['content_checksum']:raise ValueError('approved profile checksum mismatch')
        return package

    async def audit(self,revision_id: UUID):
        async with connect(self.database_url,row_factory=dict_row) as conn:
            await self._get(conn,revision_id)
            rows=await (await conn.execute('''SELECT event_id,action,actor,content_checksum,comment,created_at
                FROM goods.normalization_profile_events WHERE revision_id=%s ORDER BY created_at,event_id''',(revision_id,))).fetchall()
        return [{**dict(r),'event_id':str(r['event_id']),'created_at':r['created_at'].isoformat()} for r in rows]

    @staticmethod
    async def _get(conn,revision_id,lock=False):
        row=await (await conn.execute('SELECT * FROM goods.normalization_profile_revisions WHERE revision_id=%s'+(' FOR UPDATE' if lock else ''),(revision_id,))).fetchone()
        if row is None:raise KeyError(str(revision_id))
        return row

    @staticmethod
    async def _event(conn,row,action,actor,comment):
        await conn.execute('''INSERT INTO goods.normalization_profile_events
            (event_id,revision_id,action,actor,content_checksum,comment) VALUES (%s,%s,%s,%s,%s,%s)''',
            (uuid4(),row['revision_id'],action,actor,row['content_checksum'],comment))

    @staticmethod
    def _result(row):
        return {k:str(v) if isinstance(v,UUID) else v.isoformat() if hasattr(v,'isoformat') else v
                for k,v in row.items() if k!='package'}
