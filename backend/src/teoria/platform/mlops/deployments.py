"""Serving references and audit identity; runtime objects remain owned by the executor."""
from contextlib import asynccontextmanager

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from teoria.integrations.application_database.postgres import connect


class DeploymentRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    @asynccontextmanager
    async def lock(self, deployment_id):
        # Session transaction lock is released on cancellation or connection loss.
        async with connect(self.database_url) as connection:
            await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("mlops:" + deployment_id,))
            yield

    async def list(self):
        async with connect(self.database_url, row_factory=dict_row) as connection:
            cursor = await connection.execute("SELECT * FROM mlops.deployments ORDER BY deployment_id LIMIT 100")
            return await cursor.fetchall()

    async def get(self, deployment_id):
        async with connect(self.database_url, row_factory=dict_row) as connection:
            cursor = await connection.execute("SELECT * FROM mlops.deployments WHERE deployment_id = %s", (deployment_id,))
            return await cursor.fetchone()

    async def record(self, specification, backend, actor, run_id, status, endpoint):
        async with connect(self.database_url) as connection:
            await connection.execute("""
                INSERT INTO mlops.deployments
                    (deployment_id, backend, specification, status, requested_by, prefect_run_id, endpoint)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_id) DO UPDATE SET
                    previous_specification = CASE WHEN mlops.deployments.specification <> EXCLUDED.specification
                        THEN mlops.deployments.specification ELSE mlops.deployments.previous_specification END,
                    specification = EXCLUDED.specification, backend = EXCLUDED.backend,
                    endpoint = EXCLUDED.endpoint, status = EXCLUDED.status, requested_by = EXCLUDED.requested_by,
                    prefect_run_id = EXCLUDED.prefect_run_id, updated_at = now()
                """, (specification['deployment_id'], backend, Jsonb(specification), status, actor, run_id, endpoint))

    async def stopped(self, deployment_id, actor, run_id):
        async with connect(self.database_url) as connection:
            await connection.execute("""UPDATE mlops.deployments SET status = 'stopped',
                requested_by = %s, prefect_run_id = %s, updated_at = now() WHERE deployment_id = %s""",
                (actor, run_id, deployment_id))
