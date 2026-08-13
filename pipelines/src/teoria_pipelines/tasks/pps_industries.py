from datetime import date
from pathlib import Path
from uuid import UUID

from prefect import task
from teoria_provider.executor import ProviderExecutor
from teoria_provider.secrets import EnvironmentSecretProvider

from teoria_pipelines.connectors import PPSIndustryClient
from teoria_pipelines.models import CollectionWindow, LoadSummary
from teoria_pipelines.normalization.pps_industries import normalize_industries
from teoria_pipelines.persistence import PostgresStore
from teoria_pipelines.settings import bootstrap_pipeline_settings


PIPELINE_ID = "pps_industry_ingestion"


def _store():
    return PostgresStore(bootstrap_pipeline_settings().data_database_url or "")


@task(name="업종 사전 전체 수집", retries=2, retry_delay_seconds=300)
async def extract_industries(execution_id: UUID, pipeline_root: str):
    settings = bootstrap_pipeline_settings()
    client = PPSIndustryClient.from_pipeline_root(Path(pipeline_root), executor=ProviderExecutor(
        timeout_seconds=settings.source_timeout_seconds,
        max_attempts=settings.source_max_attempts,
        backoff_seconds=settings.source_retry_backoff_seconds,
        secret_provider=EnvironmentSecretProvider(),
    ))
    return await client.fetch_all(execution_id)


@task(name="업종 Raw 저장", retries=2)
def save_industry_raw(batch):
    return _store().save_raw_records(batch.records)


@task(name="업종 사전 정규화")
def normalize_industry_dictionary(batch, raw_count: int):
    del raw_count
    return normalize_industries(batch)


@task(name="업종 사전 스냅샷 반영", retries=2)
def load_industry_dictionary(rows):
    return LoadSummary(industries=_store().replace_procurement_industries(rows))
