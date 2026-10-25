"""Execution leases/checkpoints only; authoring state remains in Platform."""
from uuid import uuid4
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from teoria_pipelines.persistence.connection import connect
from teoria_pipelines.settings import bootstrap_pipeline_settings


class StandardWorkflowRepository:
    def __init__(self, database_url):
        if not database_url: raise ValueError('Pipeline Data DB is required')
        self.database_url = database_url

    @classmethod
    def from_environment(cls):
        return cls(bootstrap_pipeline_settings().data_database_url)

    async def claim(self, workflow_id, digest):
        lease_id = uuid4()
        async with connect(self.database_url, row_factory=dict_row) as conn:
            await conn.execute('''INSERT INTO public_procurement.specification_standard_workflows
                (workflow_id,input_checksum,status) VALUES (%s,%s,'failed') ON CONFLICT DO NOTHING''', (workflow_id,digest))
            row = await (await conn.execute('''SELECT *,lease_until>now() AS leased
                FROM public_procurement.specification_standard_workflows WHERE workflow_id=%s FOR UPDATE''', (workflow_id,))).fetchone()
            if row['input_checksum'] != digest: raise ValueError('workflow ID belongs to different inputs or code')
            if row['status'] == 'completed': return row['checkpoint'], None
            if row['leased']: raise ValueError('workflow already has an active execution')
            await conn.execute('''UPDATE public_procurement.specification_standard_workflows
                SET status='running',lease_id=%s,lease_until=now()+interval '180 seconds',error_code=NULL,
                updated_at=now() WHERE workflow_id=%s''', (lease_id,workflow_id))
        return row['checkpoint'], lease_id

    async def renew(self, workflow_id, lease_id):
        async with connect(self.database_url) as conn:
            row = await (await conn.execute('''UPDATE public_procurement.specification_standard_workflows
                SET lease_until=now()+interval '180 seconds' WHERE workflow_id=%s AND lease_id=%s
                AND lease_until>now() RETURNING workflow_id''', (workflow_id,lease_id))).fetchone()
            if row is None: raise ValueError('workflow lease lost')

    async def save(self, workflow_id, lease_id, state, *, status='running', error=None):
        release = status != 'running'
        async with connect(self.database_url) as conn:
            row = await (await conn.execute('''UPDATE public_procurement.specification_standard_workflows
                SET checkpoint=%s,status=%s,error_code=%s,updated_at=now(),
                lease_id=CASE WHEN %s THEN NULL ELSE lease_id END,
                lease_until=CASE WHEN %s THEN NULL ELSE lease_until END
                WHERE workflow_id=%s AND lease_id=%s AND lease_until>now() RETURNING workflow_id''',
                (Jsonb(state),status,error,release,release,workflow_id,lease_id))).fetchone()
            if row is None: raise ValueError('workflow lease lost')
