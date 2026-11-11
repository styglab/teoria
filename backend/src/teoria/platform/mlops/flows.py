"""Common orchestration flows; model source and dependencies stay in external images."""
from __future__ import annotations

import os
import httpx
from contextlib import asynccontextmanager

from prefect import flow, task
from prefect.runtime import flow_run

from teoria.integrations.model_execution.settings import ExecutionSettings
from teoria.platform.mlops.contracts import ServingRequest, StopRequest, TrainingRequest
from teoria.platform.mlops.deployments import DeploymentRepository


@asynccontextmanager
async def executor():
    settings = ExecutionSettings.from_environment()
    async def save_logs(run_id, data):
        from teoria.platform.mlops.artifacts import preserve_logs
        async with httpx.AsyncClient(timeout=60) as client:
            await preserve_logs(client, run_id, data)

    if settings.backend == "docker":
        from teoria.integrations.model_execution.docker import DockerExecutor
        instance = DockerExecutor(settings, log_handler=save_logs)
    elif settings.backend == "kubernetes":
        from teoria.integrations.model_execution.kubernetes import KubernetesExecutor
        instance = KubernetesExecutor(settings, log_handler=save_logs)
    else:
        raise ValueError("unsupported model execution backend")
    try:
        yield instance, settings
    finally:
        await instance.close()


@task(name="학습 실행 계약 검증", persist_result=False, retries=0)
def validate_training(execution: dict):
    return TrainingRequest.model_validate(execution)


@task(name="학습 컨테이너 실행·완료 확인", persist_result=False, retries=0)
async def execute_training(spec):
    async with executor() as (runtime, settings):
        outcome = await runtime.train(spec, str(flow_run.id))
        async with httpx.AsyncClient(timeout=60) as client:
            from teoria.platform.mlops.artifacts import verify_result
            result = await verify_result(client, spec, str(flow_run.id), settings.mlflow_url)
        return {**outcome, **result}


@flow(name="모델 이미지 학습", persist_result=False, log_prints=False)
async def train_model(execution: dict, requested_by: str):
    spec = validate_training(execution)
    return {**await execute_training(spec), "requested_by": requested_by}


@task(name="모델 서빙 배포·준비 확인·실패 복구", persist_result=False, retries=0)
async def execute_deployment(execution: dict, requested_by: str):
    spec = ServingRequest.model_validate(execution)
    repository = DeploymentRepository(os.environ["TEORIA_APP_DATABASE_URL"])
    async with repository.lock(spec.deployment_id), executor() as (runtime, settings):
        existing = await repository.get(spec.deployment_id)
        if existing and existing["status"] == "ready" and existing["backend"] != settings.backend:
            raise ValueError("stop the existing serving deployment before changing execution backend")
        result = await runtime.deploy(spec, str(flow_run.id))
        try:
            await repository.record(spec.model_dump(mode="json"), settings.backend, requested_by,
                                    str(flow_run.id), "ready", result["endpoint"])
        except BaseException:
            if existing and existing["status"] == "ready":
                await runtime.deploy(ServingRequest.model_validate(existing["specification"]), str(flow_run.id) + "-restore")
            else:
                await runtime.stop(spec.deployment_id)
            raise
        return {**result, "deployment_id": spec.deployment_id, "model_version": spec.model_version}


@flow(name="모델 이미지 서빙 배포", persist_result=False, log_prints=False)
async def deploy_model(execution: dict, requested_by: str):
    return await execute_deployment(execution, requested_by)


@task(name="모델 서빙 중지", persist_result=False, retries=0)
async def execute_stop(execution: dict, requested_by: str):
    spec = StopRequest.model_validate(execution)
    repository = DeploymentRepository(os.environ["TEORIA_APP_DATABASE_URL"])
    async with repository.lock(spec.deployment_id), executor() as (runtime, settings):
        existing = await repository.get(spec.deployment_id)
        if existing and existing["backend"] != settings.backend:
            raise ValueError("serving deployment belongs to a different execution backend")
        await runtime.stop(spec.deployment_id)
        await repository.stopped(spec.deployment_id, requested_by, str(flow_run.id))
    return {"deployment_id": spec.deployment_id, "status": "stopped"}


@flow(name="모델 이미지 서빙 중지", persist_result=False, log_prints=False)
async def stop_model(execution: dict, requested_by: str):
    return await execute_stop(execution, requested_by)


@task(name="이미지 아카이브 검증·Registry 반입", persist_result=False, retries=0)
async def execute_image_import(import_id: str):
    from uuid import UUID
    import tempfile
    from pathlib import Path
    from teoria.platform.mlops.image_imports import ImageImportRepository
    from teoria.platform.mlops.artifacts import storage
    from teoria.integrations.image_registry import ImageRegistryClient, import_docker_archive
    identifier = UUID(import_id)
    repository = ImageImportRepository(os.environ['TEORIA_APP_DATABASE_URL'])
    item = await repository.transition(identifier, ['queued'], 'importing')
    if not item:
        existing = await repository.get(identifier)
        if existing and existing['status']=='ready':return {'image':existing['image']}
        raise ValueError('image_import_not_queued')
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            store = storage(client)
            with tempfile.TemporaryDirectory(prefix='teoria-image-') as directory:
                archive = Path(directory)/'archive.bin'
                checksum = await store.download(item['archive_uri'],archive,item['size_bytes'])
                if checksum != item['sha256']:
                    raise ValueError('image_archive_checksum_mismatch')
                registry = ImageRegistryClient(client,url=os.environ['TEORIA_IMAGE_REGISTRY_URL'],
                    public_host=os.environ['TEORIA_IMAGE_REGISTRY_PUBLIC_HOST'],username=os.environ['TEORIA_IMAGE_REGISTRY_USERNAME'],
                    password=os.environ['TEORIA_IMAGE_REGISTRY_PASSWORD'])
                result = await import_docker_archive(registry,archive,directory,item['repository'],item['tag'])
            await repository.transition(identifier,['importing'],'ready',image=result['image'])
            try:await store.delete(item['archive_uri'])
            except httpx.HTTPError:pass  # Object-store lifecycle also expires abandoned imports.
            return {'image':result['image']}
    except BaseException:
        await repository.transition(identifier,['importing'],'failed',error='image_import_failed')
        raise


@flow(name="모델 이미지 반입", persist_result=False, log_prints=False)
async def import_model_image(import_id: str, requested_by: str):
    return await execute_image_import(import_id)
