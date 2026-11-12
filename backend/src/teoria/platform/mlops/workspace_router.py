"""Model settings and workload artifacts for the MLOps workspace."""
import os
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from teoria.integrations.prefect.http_client import PrefectManagementClient
from teoria.platform.mlops.artifacts import storage, TrainingResult
from teoria.platform.mlops.configurations import ConfigurationRepository, ModelConfiguration
from teoria.platform.mlops.contracts import Name, ServingRequest, TrainingRequest


class TrainingInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: UUID
    input_uri: str = Field(max_length=2048)
    input_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    parameters: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=3600, ge=1, le=604800)


class DeploymentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: UUID
    deployment_id: Name
    model_version: int = Field(ge=1, strict=True)
    model_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    replicas: int = Field(default=1, ge=1, le=16)


def create_workspace_router(*, settings, authorizer, client, registry):
    router = APIRouter(prefix='/v1/admin', tags=['model-workspace'])
    configs = ConfigurationRepository(settings.app_database_url)

    def ready():
        if not settings.model_operations_enabled or not settings.app_database_url:
            raise HTTPException(503, 'model_operations_not_configured')

    def prefect():
        if not settings.model_prefect_auth:
            raise HTTPException(503, 'prefect_not_configured')
        return PrefectManagementClient(client, settings.model_prefect_url, settings.model_prefect_auth)

    async def submit(name, parameters, actor, key):
        try:
            upstream = prefect()
            deployment = next((d for d in await upstream.deployments([name]) if d['name']==name), None)
            if not deployment or deployment.get('paused'):
                raise HTTPException(409, 'pipeline_not_available')
            run = await upstream.create_run(deployment['id'],parameters,actor=actor,key=key)
            return {'flow_run_id':run['id'],'name':run['name']}
        except httpx.HTTPError:
            raise HTTPException(503,'prefect_unavailable') from None

    async def configuration(identifier):
        ready()
        item = await configs.get(identifier)
        if not item:raise HTTPException(404,'model_configuration_not_found')
        return item

    def contract(kind, value):
        try:return kind.model_validate(value).model_dump(mode='json')
        except ValidationError:raise HTTPException(422,'invalid_execution_settings') from None

    @router.get('/model-operations/configurations')
    async def list_configurations(principal=Depends(authorizer.require())):
        ready();return {'items':await configs.list()}

    @router.post('/model-operations/configurations')
    async def save_configuration(payload: ModelConfiguration, principal=Depends(authorizer.require('metadata_admin'))):
        ready()
        if registry is None:raise HTTPException(503,'image_registry_not_configured')
        try:
            for image in {payload.image,payload.serving_image or payload.image}:
                host, remainder = image.split('/',1)
                if host != registry.host:raise HTTPException(422,'select_a_registered_image')
                repository,digest = remainder.split('@',1)
                await registry.manifest(repository,digest)
            return await configs.save(payload,principal.actor)
        except ValueError:raise HTTPException(409,'configuration_revision_conflict') from None
        except httpx.HTTPError:raise HTTPException(422,'image_not_available') from None

    @router.post('/model-operations/configurations/{identifier}/train',status_code=202)
    async def train(identifier: str, payload: TrainingInput, principal=Depends(authorizer.require('metadata_admin'))):
        item = await configuration(identifier);spec=item['specification']
        execution = contract(TrainingRequest, {
            'configuration_id':identifier,'configuration_revision':item['revision'],
            'model_name':spec['model_name'],'image':spec['image'],'command':spec['training_command'],
            'resources':spec['training_resources'],'input_uri':payload.input_uri,'input_sha256':payload.input_sha256,
            'output_uri':os.getenv('TEORIA_MODEL_RESULTS_ROOT','s3://teoria-training-results')+'/'+identifier+'/'+str(payload.idempotency_key)+'.json',
            'parameters':payload.parameters,'timeout_seconds':payload.timeout_seconds})
        return await submit('model-train',{'execution':execution,'requested_by':principal.actor},principal.actor,
                            f'{principal.actor}:config:{identifier}:train:{payload.idempotency_key}')

    @router.post('/model-operations/configurations/{identifier}/deploy',status_code=202)
    async def deploy(identifier: str, payload: DeploymentInput, principal=Depends(authorizer.require('metadata_admin'))):
        item = await configuration(identifier);spec=item['specification']
        try:
            response = await client.get(settings.model_mlflow_url.rstrip('/')+'/api/2.0/mlflow/model-versions/get',
                params={'name':spec['model_name'],'version':payload.model_version})
            response.raise_for_status(); version=response.json()['model_version']
            checksum = next((t['value'] for t in version.get('tags',[]) if t['key']=='teoria.model_sha256'),None)
            if version.get('status') not in {None,'READY'}:raise HTTPException(409,'model_version_not_ready')
            if payload.model_sha256 and checksum and payload.model_sha256 != checksum:
                raise HTTPException(409,'model_checksum_conflict')
            checksum = checksum or payload.model_sha256
            if not checksum:raise HTTPException(422,'model_checksum_required')
        except httpx.HTTPError:raise HTTPException(422,'model_version_not_available') from None
        execution = contract(ServingRequest,{
            'configuration_id':identifier,'configuration_revision':item['revision'],
            'deployment_id':payload.deployment_id,'model_name':spec['model_name'],'model_version':payload.model_version,
            'model_sha256':checksum,'image':spec.get('serving_image') or spec['image'],
            'command':spec['serving_command'],'resources':spec['serving_resources'],
            'readiness_path':spec['readiness_path'],'replicas':payload.replicas})
        return await submit('model-deploy',{'execution':execution,'requested_by':principal.actor},principal.actor,
                            f'{principal.actor}:config:{identifier}:deploy:{payload.idempotency_key}')

    @router.get('/model-operations/runs/{run_id}/logs')
    async def logs(run_id: UUID, principal=Depends(authorizer.require())):
        ready()
        try:
            deployments = await prefect().deployments(['model-train'])
            run = await prefect().run(str(run_id))
            if run.get('deployment_id') not in {d['id'] for d in deployments}:raise HTTPException(404,'model_run_not_found')
            uri = os.getenv('TEORIA_MODEL_ARTIFACT_ROOT','s3://teoria-mlops')+'/logs/'+str(run_id)+'.txt'
            body = await storage(client).get(uri,max_bytes=4*1024*1024)
            return {'text':body.decode('utf-8','replace')}
        except FileNotFoundError:raise HTTPException(404,'workload_logs_not_available') from None
        except (httpx.HTTPError,ValueError):raise HTTPException(503,'model_artifacts_unavailable') from None

    @router.get('/model-operations/runs/{run_id}/result')
    async def result(run_id: UUID, principal=Depends(authorizer.require())):
        ready()
        try:
            deployments = await prefect().deployments(['model-train'])
            run = await prefect().run(str(run_id))
            if run.get('deployment_id') not in {d['id'] for d in deployments}:raise HTTPException(404,'model_run_not_found')
            uri = run.get('parameters',{}).get('execution',{}).get('output_uri')
            if not uri:raise HTTPException(404,'training_result_not_available')
            body = await storage(client).get(uri)
            return TrainingResult.model_validate_json(body).model_dump()
        except FileNotFoundError:raise HTTPException(404,'training_result_not_available') from None
        except (httpx.HTTPError,ValueError):raise HTTPException(503,'model_artifacts_unavailable') from None

    return router
