"""Compatibility imports for existing Prefect deployment entrypoints."""

from teoria_pipelines.metadata.openmetadata import (
    run_openmetadata_ingestion_container,
    sync_openmetadata_postgres,
)

__all__ = ['run_openmetadata_ingestion_container', 'sync_openmetadata_postgres']
