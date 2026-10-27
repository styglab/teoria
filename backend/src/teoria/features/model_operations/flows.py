"""Explicit-input, manually triggered demonstration workflows."""

from __future__ import annotations

import os
import asyncio
import tempfile

from prefect import flow, task
from teoria.integrations.prefect.child_deployment import run_child_deployment
from prefect.runtime import flow_run
from prefect.artifacts import create_markdown_artifact

from teoria.features.model_operations.demo_data import (
    DATASET_VERSION,
    load_training_data,
    seed_customers,
)
from teoria.features.model_operations.training import (
    prepare_training_data,
    fit_model,
    evaluate_model,
)
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


@task(name="학습 데이터 검증·분리", persist_result=False)
async def prepare_task(values, labels):
    return await asyncio.to_thread(prepare_training_data, values, labels)


@task(name="고객 이탈 모델 학습", persist_result=False)
async def fit_task(split):
    return await asyncio.to_thread(fit_model, split)


@task(name="평가·품질 기준 확인", persist_result=False)
async def evaluate_task(model, split):
    return await asyncio.to_thread(evaluate_model, model, split)


@task(name="MLflow 모델 버전 등록", persist_result=False)
async def register_task(model, metrics, frame, checksum, requested_by):
    return await asyncio.to_thread(
        register_model,
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
    frame, split = await prepare_task(values, labels)
    model = await fit_task(split)
    metrics = await evaluate_task(model, split)
    return await register_task(model, metrics, frame, checksum, requested_by)


@flow(name="합성 고객 모델 학습·배포", persist_result=False)
async def customer_churn_pipeline(
    requested_by: str = "prefect:manual",
    deploy: bool = False,
) -> dict:
    """Train locally; deployment runs in its own pool with a real Prefect subflow link.

    Default is registration only. An explicit deploy=True authorizes demo deployment
    after the fixed quality gate. The training worker never receives a Docker socket.
    """
    result = await train_demo_customer_churn(requested_by=requested_by)
    result = {
        **result,
        "pipeline_run_id": str(flow_run.id),
        "deployment_status": "not_requested",
    }
    if deploy:
        child = await run_child_deployment(
            name="합성 고객 모델 서빙 배포/demo-deploy-customer-churn",
            parameters={
                "model_version": int(result["model_version"]),
                "requested_by": requested_by,
            },
            key=f"{flow_run.id}:deploy:{result['model_version']}",
        )
        result.update(deployment_run_id=str(child.id), deployment_status="verified")
    await create_markdown_artifact(
        key="customer-churn-release",
        markdown=(
            f"## Model release\nModel: `{result['model_name']}` v{result['model_version']}\n\n"
            f"MLflow run: `{result['run_id']}`\n\n"
            f"Dataset SHA256: `{result['dataset_checksum']}`\n\n"
            f"Deployment: {result['deployment_status']}\n\n"
            f"Deployment run: `{result.get('deployment_run_id', 'not requested')}`"
        ),
        description="Synthetic model version, dataset and deployment run references",
    )
    return result


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
