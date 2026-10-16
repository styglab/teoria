from __future__ import annotations

from teoria_pipelines.domains.public_procurement.bid_eligibility.repository import (
    EligibilityRepository,
)
from teoria_pipelines.domains.public_procurement.bid_notices.repository import (
    BidNoticeRepository,
)
from teoria_pipelines.persistence import ObjectStorage
from teoria_pipelines.settings import PipelineSettings, bootstrap_pipeline_settings


def _storage(settings: PipelineSettings) -> ObjectStorage:
    return ObjectStorage(
        settings.object_storage_endpoint or "",
        settings.object_storage_bucket,
        settings.object_storage_access_key or "",
        settings.object_storage_secret_key or "",
    )


def _resources() -> tuple[EligibilityRepository, ObjectStorage]:
    settings = bootstrap_pipeline_settings()
    return EligibilityRepository(settings.data_database_url or ""), _storage(settings)


def _document_resources() -> tuple[BidNoticeRepository, ObjectStorage]:
    settings = bootstrap_pipeline_settings()
    return BidNoticeRepository(settings.data_database_url or ""), _storage(settings)
