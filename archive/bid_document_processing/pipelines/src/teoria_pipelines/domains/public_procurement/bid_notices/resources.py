from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from teoria_provider_api.executor import ProviderExecutor
from teoria_provider_api.secrets import EnvironmentSecretProvider

from teoria_pipelines.domains.public_procurement.bid_notices.client import (
    PPSBidNoticeClient,
)
from teoria_pipelines.domains.public_procurement.bid_notices.models import (
    NormalizedBidNoticeBatch,
)
from teoria_pipelines.domains.public_procurement.bid_notices.repository import (
    BidNoticeRepository,
)
from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.models import CollectionWindow, ExtractedBatch
from teoria_pipelines.persistence import ObjectStorage
from teoria_pipelines.settings import bootstrap_pipeline_settings

PIPELINE_ID = "pps_bid_notice_ingestion"


BACKFILL_PIPELINE_ID = "pps_bid_notice_backfill_2021_2026"


ENRICHMENT_BACKFILL_PIPELINE_ID = "pps_bid_notice_enrichment_backfill"


from teoria_pipelines.domains.public_procurement.bid_notices.client import (
    NOTICE_OPERATIONS as NOTICE_OPERATIONS,
)

SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")


VIZ_WINDOW = CollectionWindow(date(2026, 8, 1), date(2026, 8, 1))


VIZ_EXTRACTED = ExtractedBatch(execution_id=UUID(int=0), window=VIZ_WINDOW)


VIZ_NORMALIZED = NormalizedBidNoticeBatch()


VIZ_SUMMARY = LoadSummary()


VIZ_NOTICE_LOAD = (VIZ_SUMMARY, [])


def _store() -> BidNoticeRepository:
    settings = bootstrap_pipeline_settings()
    return BidNoticeRepository(settings.data_database_url or "")


def _client(pipeline_root: str) -> PPSBidNoticeClient:
    settings = bootstrap_pipeline_settings()
    return PPSBidNoticeClient.from_pipeline_root(
        Path(pipeline_root),
        executor=ProviderExecutor(
            timeout_seconds=settings.source_timeout_seconds,
            max_attempts=settings.source_max_attempts,
            backoff_seconds=settings.source_retry_backoff_seconds,
            secret_provider=EnvironmentSecretProvider(),
        ),
        enrichment_requests_per_second=(
            settings.bid_notice_enrichment_requests_per_second
        ),
    )


def _object_storage() -> ObjectStorage:
    settings = bootstrap_pipeline_settings()
    if not all(
        (
            settings.object_storage_endpoint,
            settings.object_storage_access_key,
            settings.object_storage_secret_key,
        )
    ):
        raise ValueError("bid document object storage configuration is required")
    return ObjectStorage(
        settings.object_storage_endpoint or "",
        settings.object_storage_bucket,
        settings.object_storage_access_key or "",
        settings.object_storage_secret_key or "",
    )
