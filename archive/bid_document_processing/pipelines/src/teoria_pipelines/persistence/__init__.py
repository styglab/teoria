"""Data Pipeline persistence adapters."""
from teoria_pipelines.persistence.postgres import PostgresStore
from teoria_pipelines.persistence.object_storage import ObjectStorage

__all__ = ["ObjectStorage", "PostgresStore"]
