"""Explicit-input, manually triggered demonstration workflows."""

from __future__ import annotations

import os
import tempfile

from prefect import flow, task

from teoria.features.model_operations.demo_data import (
    DATASET_VERSION,
    load_training_data,
    seed_customers,
)
from teoria.features.model_operations.training import fit_customer_churn
from teoria.integrations.mlflow.models import (
    MODEL_NAME,
    download_version,
    register_model,
)
from teoria.integrations.model_serving.docker import activate_demo_release


@task(name="합성 고객·이용 이력 적재", persist_result=False)
async def seed_task() -> dict:
    return await seed_customers(os.environ["TEORIA_PIPELINE_DATA_DATABASE_URL"])


@flow(name="합성 고객 데이터 준비", persist_result=False)
async def seed_demo_customers(requested_by: str = "prefect:manual") -> dict:
    return await seed_task()


@task(name="식별정보 제외 학습 snapshot 조회", persist_result=False)
async def read_training_task():
    return await load_training_data(os.environ["TEORIA_PIPELINE_DATA_DATABASE_URL"])


@task(name="학습·평가 및 MLflow 모델 등록", persist_result=False)
def train_task(values, labels, checksum, requested_by):
    model, metrics, frame = fit_customer_churn(values, labels)
    return register_model(
        model,
        metrics,
        frame,
        dataset_version=DATASET_VERSION,
        dataset_checksum=checksum,
        requested_by=requested_by,
    )


@flow(name="합성 고객 이탈 모델 학습", persist_result=False)
async def train_demo_customer_churn(requested_by: str = "prefect:manual") -> dict:
    values, labels, checksum = await read_training_task()
    return train_task(values, labels, checksum, requested_by)


@task(name="고정 모델 다운로드·checksum 검증·서빙 전환", persist_result=False)
def deploy_task(model_version: int, requested_by: str):
    if (
        isinstance(model_version, bool)
        or not isinstance(model_version, int)
        or model_version < 1
    ):
        raise ValueError("model_version must be a positive integer")
    with tempfile.TemporaryDirectory() as directory:
        _, checksum = download_version(model_version, directory)
    return activate_demo_release(
        {
            "model_name": MODEL_NAME,
            "model_version": model_version,
            "sha256": checksum,
            "requested_by": requested_by,
            "synthetic": True,
        }
    )


@flow(name="합성 고객 모델 서빙 배포", persist_result=False)
def deploy_demo_customer_churn(
    model_version: int, requested_by: str = "prefect:manual"
) -> dict:
    return deploy_task(model_version, requested_by)
