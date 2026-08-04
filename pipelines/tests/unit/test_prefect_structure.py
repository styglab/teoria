from inspect import Parameter, signature
from pathlib import Path

import yaml

from teoria_pipelines.flows.pps_contracts import (
    sync_pps_contract_backfill,
    sync_pps_contract_incremental,
    sync_pps_contract_window,
    sync_pps_contracts,
)
from teoria_pipelines.tasks.pps_contracts import extract_contract_operation


PIPELINES = Path(__file__).parents[2]
from teoria_pipelines.tasks.pps_contracts import (
    complete_pipeline_run,
    combine_extracted_batches,
    determine_collection_window,
    extract_contract_operation,
    normalize_contracts,
    save_raw_records,
    update_checkpoint,
    upsert_contracts,
)


def test_prefect_flow_and_task_names_are_operationally_readable() -> None:
    assert sync_pps_contracts.name == "나라장터 계약정보 수집"
    assert sync_pps_contract_incremental.name == "나라장터 계약정보 증분 수집"
    assert sync_pps_contract_backfill.name == "나라장터 계약정보 Backfill"
    assert sync_pps_contract_window.name == "나라장터 계약정보 일별 수집"
    assert [
        determine_collection_window.name,
        extract_contract_operation.name,
        combine_extracted_batches.name,
        save_raw_records.name,
        normalize_contracts.name,
        upsert_contracts.name,
        update_checkpoint.name,
        complete_pipeline_run.name,
    ] == [
        "수집 구간 결정",
        "나라장터 Operation 수집",
        "Operation 응답 결합",
        "Raw 응답 저장",
        "계약정보 정규화",
        "정규 테이블 Upsert",
        "Checkpoint 갱신",
        "수집 실행 완료",
    ]


def test_daily_flow_mermaid_graph_exposes_execution_order() -> None:
    graph = sync_pps_contract_window.generate_mermaid_graph(
        window=CollectionWindow(date(2026, 7, 1), date(2026, 7, 1)),
        pipeline_root="pipelines",
    )

    assert "수집_실행_시작_0 --> 상품_계약_API_수집_0" in graph
    assert "상품_계약_API_수집_0 --> 공사_계약_API_수집_0" in graph
    assert "외자_계약_API_수집_0 --> Operation_응답_결합_0" in graph
    assert "Operation_응답_결합_0 --> Raw_응답_저장_0" in graph
    assert "Raw_응답_저장_0 --> 계약정보_정규화_0" in graph
    assert "정규_테이블_Upsert_0 --> Checkpoint_갱신_0" in graph
    assert "Checkpoint_갱신_0 --> 수집_실행_완료_0" in graph


def test_backfill_deployment_has_a_fixed_2026_range() -> None:
    prefect = yaml.safe_load((PIPELINES / "prefect.yaml").read_text(encoding="utf-8"))
    deployment = next(
        item for item in prefect["deployments"] if item["name"] == "pps-contract-backfill"
    )

    assert deployment["parameters"] == {
        "checkpoint_id": "pps_contract_backfill_2026",
        "start_date": "2026-01-01",
        "end_date": "2026-07-31",
        "pipeline_root": "/app/pipelines",
        "batch_days": 30,
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


def test_incremental_deployment_prevents_overlapping_runs() -> None:
    prefect = yaml.safe_load((PIPELINES / "prefect.yaml").read_text(encoding="utf-8"))
    deployment = next(
        item for item in prefect["deployments"] if item["name"] == "pps-contract-incremental"
    )

    assert deployment["concurrency_limit"] == {
        "limit": 1,
        "collision_strategy": "CANCEL_NEW",
    }


def test_operation_task_retries_once_after_five_minutes() -> None:
    assert extract_contract_operation.retries == 1
    assert extract_contract_operation.retry_delay_seconds == 300
from datetime import date

from teoria_pipelines.models import CollectionWindow
