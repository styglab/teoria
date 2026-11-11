"""Reusable model execution settings and optimistic configuration updates."""
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from teoria.integrations.application_database.postgres import connect
from teoria.platform.mlops.contracts import Image, ImageExecution, ModelName, Name, Resources


class ModelConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Name
    model_name: ModelName
    image: Image
    serving_image: Image | None = None
    training_command: list[str] = Field(min_length=1, max_length=64)
    serving_command: list[str] = Field(min_length=1, max_length=64)
    training_resources: Resources = Field(default_factory=Resources)
    serving_resources: Resources = Field(default_factory=Resources)
    readiness_path: str = Field(default="/health", pattern=r"^/[a-zA-Z0-9/_-]*$", max_length=200)
    revision: int | None = Field(default=None, ge=1)

    @field_validator("training_command", "serving_command")
    @classmethod
    def bounded_commands(cls, value):
        return ImageExecution.command_is_bounded(value)


class ConfigurationRepository:
    def __init__(self, database_url):
        self.database_url = database_url

    async def list(self):
        async with connect(self.database_url, row_factory=dict_row) as connection:
            return await (await connection.execute("SELECT * FROM mlops.configurations ORDER BY updated_at DESC LIMIT 100")).fetchall()

    async def get(self, identifier):
        async with connect(self.database_url, row_factory=dict_row) as connection:
            return await (await connection.execute("SELECT * FROM mlops.configurations WHERE id=%s", (identifier,))).fetchone()

    async def save(self, value, actor):
        async with connect(self.database_url, row_factory=dict_row) as connection:
            # Serializes creation as well as updates; a caller must present the revision it edited.
            await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("model-config:"+value.id,))
            existing = await (await connection.execute("SELECT * FROM mlops.configurations WHERE id=%s FOR UPDATE", (value.id,))).fetchone()
            if (existing and value.revision != existing['revision']) or (not existing and value.revision is not None):
                raise ValueError("configuration_revision_conflict")
            revision = (existing['revision'] if existing else 0) + 1
            specification = value.model_dump(mode="json", exclude={"revision"})
            return await (await connection.execute("""INSERT INTO mlops.configurations
                (id,revision,specification,created_by,updated_by) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET revision=EXCLUDED.revision,specification=EXCLUDED.specification,
                    updated_by=EXCLUDED.updated_by,updated_at=now() RETURNING *""",
                (value.id,revision,Jsonb(specification),actor,actor))).fetchone()
