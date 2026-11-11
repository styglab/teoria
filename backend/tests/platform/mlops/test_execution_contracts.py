import pytest
from pydantic import ValidationError

from teoria.platform.mlops.contracts import TrainingRequest, ServingRequest, validate_execution
from teoria.integrations.model_execution.settings import ExecutionSettings
from teoria.integrations.model_execution.kubernetes import training_manifest, serving_manifest

IMAGE = 'registry.example.com/models/test@sha256:' + 'a' * 64


def training(**changes):
    return TrainingRequest.model_validate(dict(image=IMAGE, command=['python','train.py'], model_name='test',
        input_uri='s3://datasets/v1/data.csv', input_sha256='b'*64, output_uri='s3://models/run-1', **changes))


def serving(**changes):
    return ServingRequest.model_validate(dict(image=IMAGE, command=['python','serve.py'], deployment_id='test',
        model_name='test', model_version=1, model_sha256='b'*64, **changes))


def settings(monkeypatch):
    monkeypatch.setenv('TEORIA_MODEL_ALLOWED_REGISTRIES','registry.example.com')
    return ExecutionSettings.from_environment()


@pytest.mark.parametrize("kind,spec", [("training", training), ("serving", serving)])
def test_execution_requires_an_explicit_valid_command(kind, spec):
    payload = spec().model_dump(exclude={"command"})
    with pytest.raises(ValidationError):
        validate_execution(kind, payload)
    for command in ([], ["python", ""], ["python", "train\x00"]):
        with pytest.raises(ValidationError):
            validate_execution(kind, {**payload, "command": command})


def test_portable_contract_rejects_privileges_and_credentials():
    for field, value in [('volumes',['/var/run/docker.sock']), ('environment',{'TOKEN':'secret'}), ('privileged',True)]:
        with pytest.raises(ValidationError):
            TrainingRequest.model_validate({**training().model_dump(),field:value})
    for image in ['registry.example.com/test:latest', 'https://registry.example.com/test@sha256:'+'a'*64]:
        with pytest.raises(ValidationError):
            TrainingRequest.model_validate({**training().model_dump(),'image':image})
    with pytest.raises(ValidationError):
        training(parameters={'api_key':'secret'})
    for uri in ['file:///etc/passwd', 's3://user:password@bucket/data', 'https://example.com/data', 's3://bucket/data?token=secret']:
        with pytest.raises(ValidationError):
            TrainingRequest.model_validate({**training().model_dump(),'input_uri':uri})


def test_kubernetes_training_is_bounded_and_has_no_control_plane_credentials(monkeypatch):
    policy = settings(monkeypatch)
    manifest = training_manifest(training(resources={'cpu':2,'memory_mib':2048,'gpu':1}), 'run-1', policy)
    job = manifest['spec'];pod=job['template']['spec'];container=pod['containers'][0]
    assert job['backoffLimit']==0 and job['activeDeadlineSeconds']==3600
    assert pod['automountServiceAccountToken'] is False
    assert 'volumes' not in pod
    assert container['command']==['python','train.py']
    assert container['resources']['limits']=={'cpu':'2.0','memory':'2048Mi','nvidia.com/gpu':'1'}
    assert container['securityContext']['allowPrivilegeEscalation'] is False
    assert {e['name'] for e in container['env']}.isdisjoint({'PREFECT_API_AUTH_STRING','TEORIA_APP_DATABASE_URL'})
    assert training_manifest(training(), 'run-1', policy)['metadata']['name']==manifest['metadata']['name']


def test_kubernetes_serving_uses_fixed_version_and_readiness_gated_update(monkeypatch):
    deployment, service = serving_manifest(serving(replicas=2), settings(monkeypatch))
    assert deployment['spec']['replicas']==2
    assert deployment['spec']['strategy']['rollingUpdate']['maxUnavailable']==0
    env={e['name']:e['value'] for e in deployment['spec']['template']['spec']['containers'][0]['env']}
    assert env['TEORIA_MODEL_URI']=='models:/test/1'
    assert env['TEORIA_MODEL_SHA256']=='b'*64
    assert service['spec']['selector']==deployment['spec']['selector']['matchLabels']


def test_unknown_registry_is_rejected(monkeypatch):
    policy=settings(monkeypatch)
    with pytest.raises(ValueError, match='not allowed'):
        policy.validate_image('other.example.com/image@sha256:'+'a'*64)
    monkeypatch.delenv('TEORIA_MODEL_ALLOWED_REGISTRIES')
    with pytest.raises(ValueError, match='not allowed'):
        ExecutionSettings.from_environment().validate_image(IMAGE)
