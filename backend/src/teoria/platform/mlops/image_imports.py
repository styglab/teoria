"""Persistent image archive import state; payload bytes live in object storage."""
from pydantic import BaseModel, ConfigDict, Field
from psycopg.rows import dict_row

from teoria.integrations.application_database.postgres import connect
from teoria.integrations.image_registry import REPOSITORY, TAG


class ImageImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str = Field(pattern=f"^{REPOSITORY}$", max_length=255)
    tag: str = Field(pattern=f"^{TAG}$", max_length=128)
    size_bytes: int = Field(gt=0, le=10*1024**3)


class ImageImportRepository:
    def __init__(self, database_url):
        self.database_url = database_url

    async def list(self):
        async with connect(self.database_url, row_factory=dict_row) as connection:
            return await (await connection.execute("SELECT * FROM mlops.image_imports ORDER BY created_at DESC LIMIT 100")).fetchall()

    async def get(self, identifier):
        async with connect(self.database_url, row_factory=dict_row) as connection:
            return await (await connection.execute("SELECT * FROM mlops.image_imports WHERE id=%s", (identifier,))).fetchone()

    async def create(self, identifier, value, actor):
        async with connect(self.database_url, row_factory=dict_row) as connection:
            return await (await connection.execute("""INSERT INTO mlops.image_imports
                (id,repository,tag,size_bytes,status,created_by) VALUES (%s,%s,%s,%s,'created',%s) RETURNING *""",
                (identifier,value.repository,value.tag,value.size_bytes,actor))).fetchone()

    async def transition(self, identifier, old, new, **values):
        allowed = {"sha256","archive_uri","image","prefect_run_id","error"}
        if set(values)-allowed:
            raise ValueError("invalid import update")
        sets = ["status=%s", "updated_at=now()"] + [key+"=%s" for key in values]
        async with connect(self.database_url, row_factory=dict_row) as connection:
            return await (await connection.execute("UPDATE mlops.image_imports SET "+','.join(sets)+
                " WHERE id=%s AND status=ANY(%s) RETURNING *", (new,*values.values(),identifier,list(old)))).fetchone()

    async def queue(self, identifier):
        async with connect(self.database_url, row_factory=dict_row) as connection:
            return await (await connection.execute("""UPDATE mlops.image_imports SET status='queued',
                attempt=attempt+1,error=NULL,prefect_run_id=NULL,updated_at=now()
                WHERE id=%s AND status IN ('uploaded','failed') AND archive_uri IS NOT NULL RETURNING *""", (identifier,))).fetchone()
