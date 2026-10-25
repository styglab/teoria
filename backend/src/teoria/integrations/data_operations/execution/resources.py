from __future__ import annotations

from teoria.integrations.data_operations.persistence import PostgresStore
from teoria.integrations.data_operations.settings import bootstrap_pipeline_settings


def _store() -> PostgresStore:
    settings = bootstrap_pipeline_settings()
    return PostgresStore(settings.data_database_url or "")
