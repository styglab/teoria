from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID

import yaml
from prefect import task
from prefect.cache_policies import NO_CACHE

from teoria_pipelines.domains.legal_information.laws.models import LawTarget
from teoria_pipelines.domains.legal_information.laws.parsing import parse_law
from teoria_pipelines.domains.legal_information.laws.repository import LawRepository
from teoria_pipelines.settings import bootstrap_pipeline_settings

PIPELINE_ID = "moleg_law_ingestion"


def repository() -> LawRepository:
    return LawRepository(bootstrap_pipeline_settings().data_database_url or "")


@task(name="법령 수집 대상 확인", persist_result=False)
def load_targets(pipeline_root: str, target_ids: list[str] | None = None) -> list[LawTarget]:
    from teoria_pipelines.loader import UniqueKeyLoader
    document = yaml.load((Path(pipeline_root) / "config/law_targets.yaml").read_text(), Loader=UniqueKeyLoader)
    if not isinstance(document, dict) or set(document) != {"laws"} or not isinstance(document["laws"], list):
        raise ValueError("invalid_law_targets")
    targets = [LawTarget.model_validate(value) for value in document["laws"]]
    if not targets or len({t.id for t in targets}) != len(targets):
        raise ValueError("invalid_law_targets")
    if target_ids is not None:
        if not target_ids or set(target_ids) - {t.id for t in targets}:
            raise ValueError("unknown_law_target")
        targets = [t for t in targets if t.id in target_ids]
    return targets


@task(name="법령 수집 실행 기록", persist_result=False)
def start_law_run(execution_id: UUID, reconcile_all: bool, target_count: int):
    repository().start_run(execution_id, reconcile_all, target_count)


@task(name="법령 ID 확인", cache_policy=NO_CACHE, persist_result=False)
async def resolve_law_target(client, target):
    pinned = repository().pinned_law_id(target.id)
    if pinned:
        if target.law_id and pinned != target.law_id:
            raise ValueError("law_target_identity_changed")
        return pinned, []
    return await client.resolve_target(target)


@task(name="법령 버전 목록 전체 수집", cache_policy=NO_CACHE, persist_result=False)
async def collect_law_catalog(client, law_id: str):
    return await client.collect_catalog(law_id)


@task(name="법령 원본 XML 보관", retries=2, retry_delay_seconds=5, persist_result=False)
def save_law_raw(execution_id, responses):
    store = repository()
    return [store.save_raw(execution_id, response) for response in responses]


@task(name="법령 목록 등록 및 수집 버전 선택", persist_result=False)
def select_law_versions(target, catalog, reconcile_all: bool, today: date):
    store = repository()
    store.register_catalog(target, catalog)
    return store.select_versions(catalog, reconcile_all=reconcile_all, today=today)


@task(name="시행일별 법령 본문 수집", cache_policy=NO_CACHE, persist_result=False)
async def fetch_law_version(client, version):
    return await client.fetch_version(version)


@task(name="법령 조항 구조화 및 버전 검증", persist_result=False)
def normalize_law(response, version):
    return parse_law(response.raw_body, version)


@task(name="법령 스냅샷 및 조항 적재", retries=2, retry_delay_seconds=5, persist_result=False)
def load_law_snapshot(parsed, response, source_hash):
    return repository().save_snapshot(parsed, response, source_hash)


@task(name="법령 수집 진행 기록", persist_result=False)
def record_law_progress(execution_id, catalog_count, collected, provisions, failed_targets):
    repository().record_progress(execution_id, catalog_count, collected, provisions, failed_targets)


@task(name="저장 원문 재가공 대상 조회", persist_result=False)
def stored_law_versions(target_id: str | None, reparse_all: bool):
    from teoria_pipelines.domains.legal_information.laws.parsing import PARSER_VERSION
    return [r for r in repository().stored_versions(target_id)
            if r['snapshot_id'] and (reparse_all or r['parser_version'] != PARSER_VERSION)]


@task(name="저장 법령 원문 읽기", persist_result=False)
def read_archived_law(row):
    from teoria_pipelines.domains.legal_information.laws.models import LawVersion
    version = LawVersion(row['law_id'],row['mst'],row['effective_date'],row['name'],
        row['promulgation_date'],row['promulgation_number'],row['amendment_type'],row['listing'])
    return version, repository().archived_response(row)
