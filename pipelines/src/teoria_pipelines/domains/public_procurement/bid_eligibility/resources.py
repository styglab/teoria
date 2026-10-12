from __future__ import annotations

from teoria_pipelines.persistence import ObjectStorage, PostgresStore
from teoria_pipelines.settings import bootstrap_pipeline_settings


def _resources() -> tuple[PostgresStore, ObjectStorage]:
    settings = bootstrap_pipeline_settings()
    storage = ObjectStorage(settings.object_storage_endpoint or "", settings.object_storage_bucket,
                            settings.object_storage_access_key or "",
                            settings.object_storage_secret_key or "")
    return PostgresStore(settings.data_database_url or ""), storage
