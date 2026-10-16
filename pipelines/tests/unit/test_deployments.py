from inspect import Parameter, signature
from pathlib import Path
import yaml
from teoria_pipelines.domains.public_procurement.contracts.flows import (
    retry_pps_contract_backfill_gaps,
    sync_pps_contract_backfill,
)
from teoria_pipelines.domains.public_procurement.bid_notices.flows import (
    sync_pps_bid_notice_backfill,
    sync_pps_bid_notice_enrichment_backfill,
    sync_pps_bid_notice_window,
    sync_pps_bid_notices,
)


PIPELINES = Path(__file__).resolve().parents[2]


def test_archived_document_jobs_are_absent_from_supported_deployments() -> None:
    deployments = yaml.safe_load((PIPELINES / "prefect.yaml").read_text())["deployments"]
    assert all("bid-document" not in item["name"] for item in deployments)
    assert all("bid-eligibility" not in item["name"] for item in deployments)
    assert all(item["work_pool"]["name"] != "teoria-ai-extraction" for item in deployments)


def test_backfill_deployment_has_a_fixed_historical_range() -> None:
    prefect = yaml.safe_load((PIPELINES / "prefect.yaml").read_text(encoding="utf-8"))
    deployment = next(
        item
        for item in prefect["deployments"]
        if item["name"] == "pps-contract-backfill"
    )

    assert deployment["parameters"] == {
        "checkpoint_id": "pps_contract_backfill_2021_2026",
        "start_date": "2021-01-01",
        "end_date": "2026-09-13",
        "pipeline_root": "/app/pipelines",
        "batch_days": 7,
    }
    assert deployment["schedules"][0] == {
        "cron": "20 4 * * *",
        "timezone": "Asia/Seoul",
        "active": True,
    }
    assert deployment["concurrency_limit"] == {
        "limit": 1,
        "collision_strategy": "CANCEL_NEW",
    }

    parameters = signature(sync_pps_contract_backfill.fn).parameters
    assert all(
        parameters[name].default is Parameter.empty
        for name in ("checkpoint_id", "start_date", "end_date")
    )

    gap_retry = next(
        item
        for item in prefect["deployments"]
        if item["name"] == "pps-contract-backfill-gap-retry"
    )
    assert gap_retry["parameters"] == {
        "pipeline_root": "/app/pipelines",
        "source_pipeline_id": "pps_contract_backfill_2021_2026",
        "batch_size": 1,
        "retry_days": 1,
        "max_attempts": 15,
    }
    assert gap_retry["schedules"][0] == {
        "cron": "20 5 * * *",
        "timezone": "Asia/Seoul",
        "active": True,
    }
    assert (
        retry_pps_contract_backfill_gaps.name
        == "나라장터 계약정보 Backfill 결손 재처리"
    )


def test_bid_opening_backfill_uses_accelerated_non_overlapping_schedule() -> None:
    prefect = yaml.safe_load((PIPELINES / "prefect.yaml").read_text(encoding="utf-8"))
    deployment = next(
        item
        for item in prefect["deployments"]
        if item["name"] == "pps-bid-opening-backfill-enrichment"
    )

    assert deployment["parameters"] == {
        "pipeline_root": "/app/pipelines",
        "batch_size": 180,
        "lease_minutes": 30,
        "queue_mode": "backfill",
    }
    assert deployment["schedules"][0] == {
        "cron": "1-59/5 * * * *",
        "timezone": "Asia/Seoul",
        "active": True,
    }
    assert deployment["concurrency_limit"] == {
        "limit": 1,
        "collision_strategy": "CANCEL_NEW",
    }


def test_incremental_deployment_prevents_overlapping_runs() -> None:
    prefect = yaml.safe_load((PIPELINES / "prefect.yaml").read_text(encoding="utf-8"))
    deployment = next(
        item
        for item in prefect["deployments"]
        if item["name"] == "pps-contract-incremental"
    )

    assert deployment["concurrency_limit"] == {
        "limit": 1,
        "collision_strategy": "CANCEL_NEW",
    }


def test_openmetadata_ingestion_uses_isolated_worker_and_is_opt_in() -> None:
    prefect = yaml.safe_load(
        (PIPELINES / "prefect.metadata.yaml").read_text(encoding="utf-8")
    )
    deployment = next(
        item
        for item in prefect["deployments"]
        if item["name"] == "openmetadata-postgres-metadata-sync"
    )

    assert deployment["work_pool"]["name"] == "teoria-metadata"
    assert deployment["parameters"] == {
        "image": "teoria-openmetadata-ingestion:2.0.5",
        "network": "teoria_default",
        "timeout_seconds": 1800,
    }
    assert deployment["schedules"][0] == {
        "cron": "0 5 * * *",
        "timezone": "Asia/Seoul",
        "active": True,
    }


def test_bid_notice_deployments_are_frequent_and_staggered() -> None:
    prefect = yaml.safe_load((PIPELINES / "prefect.yaml").read_text(encoding="utf-8"))
    notices = next(
        item
        for item in prefect["deployments"]
        if item["name"] == "pps-bid-notice-ingestion"
    )
    backfill = next(
        item
        for item in prefect["deployments"]
        if item["name"] == "pps-bid-notice-backfill"
    )
    enrichment_backfill = next(
        item
        for item in prefect["deployments"]
        if item["name"] == "pps-bid-notice-enrichment-backfill"
    )
    reconciliation = next(
        item
        for item in prefect["deployments"]
        if item["name"] == "pps-bid-notice-reconciliation-3d"
    )
    assert notices["schedules"][0]["cron"] == "0 * * * *"
    assert notices["parameters"] == {
        "pipeline_root": "/app/pipelines",
        "lookback_days": 1,
        "enrichment_batch_size": 20,
    }
    assert reconciliation["schedules"][0] == {
        "cron": "10 1 * * *",
        "timezone": "Asia/Seoul",
        "active": False,
    }
    assert reconciliation["parameters"]["lookback_days"] == 3
    assert backfill["schedules"][0] == {
        "cron": "50 * * * *",
        "timezone": "Asia/Seoul",
        "active": True,
    }
    assert backfill["parameters"] == {
        "checkpoint_id": "pps_bid_notice_backfill_2021_2026",
        "start_date": "2021-01-01",
        "end_date": "2026-09-13",
        "pipeline_root": "/app/pipelines",
        "batch_days": 7,
    }
    assert backfill["concurrency_limit"] == {
        "limit": 1,
        "collision_strategy": "CANCEL_NEW",
    }
    assert enrichment_backfill["schedules"][0] == {
        "cron": "25 * * * *",
        "timezone": "Asia/Seoul",
        "active": True,
    }
    assert enrichment_backfill["parameters"] == {
        "pipeline_root": "/app/pipelines",
        "batch_size": 20,
        "chunk_size": 5,
        "minimum_age_days": 7,
        "lease_minutes": 60,
    }
    assert sync_pps_bid_notices.name == "나라장터 입찰공고·참가제한 수집"
    assert sync_pps_bid_notice_window.name == "나라장터 입찰공고 일별 구간 수집"
    assert sync_pps_bid_notice_backfill.name == "나라장터 입찰공고 Backfill"
    assert (
        sync_pps_bid_notice_enrichment_backfill.name
        == "나라장터 입찰공고 참가제한 Backfill"
    )



def test_contract_and_bid_result_reconciliation_schedules_are_layered() -> None:
    deployments = {
        item["name"]: item
        for item in yaml.safe_load(
            (PIPELINES / "prefect.yaml").read_text(encoding="utf-8")
        )["deployments"]
    }

    assert deployments["pps-contract-incremental"]["parameters"]["lookback_days"] == 3
    assert deployments["pps-bid-result-incremental"]["parameters"]["lookback_days"] == 3
    assert (
        deployments["pps-contract-reconciliation-30d"]["schedules"][0]["cron"]
        == "0 2 * * *"
    )
    assert (
        deployments["pps-contract-reconciliation-90d"]["schedules"][0]["cron"]
        == "0 3 * * 0"
    )
    assert (
        deployments["pps-bid-result-reconciliation-30d"]["schedules"][0]["cron"]
        == "30 2 * * *"
    )
    assert (
        deployments["pps-bid-result-reconciliation-90d"]["schedules"][0]["cron"]
        == "30 3 * * 0"
    )
