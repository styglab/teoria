"""One portable Teoria deployment with independent foundation lifecycles."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
KUBE = ROOT / "deploy/kubernetes"


@pytest.fixture
def kubectl(tmp_path):
    executable=os.getenv('TEORIA_TEST_KUBECTL') or shutil.which('kubectl')
    if not executable:
        pytest.skip('kubectl is required for offline kustomize rendering')
    # Fail immediately if an offline test accidentally attempts cluster access.
    wrapper=tmp_path/'kubectl'
    wrapper.write_text('''#!/usr/bin/env python3
import os,sys
if len(sys.argv) < 2 or sys.argv[1] != 'kustomize':
    raise SystemExit('offline rendering attempted cluster access')
os.execv(os.environ['TEORIA_TEST_REAL_KUBECTL'], [os.environ['TEORIA_TEST_REAL_KUBECTL'], *sys.argv[1:]])
''')
    wrapper.chmod(0o755)
    return {**os.environ,'PATH':str(tmp_path)+os.pathsep+os.environ['PATH'],
            'TEORIA_TEST_REAL_KUBECTL':str(Path(executable).resolve()),'KUBECONFIG':str(tmp_path/'not-present')}


def render(environment, overlay="generic", component="all", *options):
    args = ["bash", str(KUBE / "deploy.sh"), "ghcr.io/example/teoria", "a" * 40,
            "teoria.example.com", "--component", component, "--overlay", overlay, "--render"]
    if overlay == "generic" and component in {"platform", "all"}:
        args += ["--shared-storage-class", "cluster-rwx"]
    result = subprocess.run(args + list(options), env=environment, text=True, capture_output=True, check=True)
    return [r for r in yaml.safe_load_all(result.stdout) if r]


def identity(resource):
    return resource["apiVersion"], resource["kind"], resource["metadata"].get("namespace", ""), resource["metadata"]["name"]


def test_resource_definitions_have_one_owner():
    definitions = {}
    for path in (KUBE / "base").rglob("*.yaml"):
        assert path.relative_to(KUBE / "base").parts[0] in {"teoria", "services", "domains"}
        for resource in yaml.safe_load_all(path.read_text()):
            if resource["kind"] == "Kustomization":
                continue
            key = identity(resource)
            assert key not in definitions, (key, definitions.get(key), path)
            definitions[key] = path
            if resource["kind"] == "PersistentVolumeClaim":
                assert "storageClassName" not in resource["spec"]
    assert not (KUBE / "profiles").exists()


@pytest.mark.parametrize("overlay", ["generic", "k3s", "k3d"])
def test_platform_always_combines_metadata_ontology_and_mlops(kubectl, overlay):
    resources = render(kubectl, overlay)
    assert len({identity(r) for r in resources}) == len(resources)
    assert all(not r["apiVersion"].startswith("traefik") for r in resources)
    workloads = {r["metadata"]["name"]: r for r in resources if r["kind"] in {"Deployment", "StatefulSet"}}
    assert {"admin-api", "admin-ui", "runtime-api", "opa", "policy-control-plane", "prefect-metadata-worker",
            "model-training-worker", "postgres", "platform-postgres", "openmetadata-server", "openmetadata-search",
            "mlflow", "minio", "prefect-server", "prefect-services", "prefect-redis"} <= workloads.keys()
    admin = workloads["admin-api"]["spec"]["template"]["spec"]["containers"][0]
    env = {e["name"]: e for e in admin["env"]}
    for key in ("TEORIA_SEMANTIC_MODELING_ENABLED", "TEORIA_MODEL_OPERATIONS_ENABLED", "TEORIA_OPENMETADATA_ENABLED"):
        assert env[key]["value"] == "true"
    assert "TEORIA_FEATURES" not in env
    for key in ("TEORIA_FORMATID_ENABLED", "TEORIA_GOODS_AUTHORING_ENABLED", "TEORIA_LEGAL_INFORMATION_ENABLED"):
        assert "configMapKeyRef" in env[key]["valueFrom"]
    assert env["TEORIA_RUNTIME_ARTIFACT_STORE"]["value"] == "/app/runtime_artifacts"
    assert admin["image"] == "ghcr.io/example/teoria/authoring:" + "a" * 40
    assert workloads["prefect-worker"]["spec"]["replicas"] == 0
    assert workloads["prefect-law-worker"]["spec"]["replicas"] == 0
    jobs = {r["metadata"]["name"]: r for r in resources if r["kind"] == "Job"}
    assert {"metadata-register", "model-register", "goods-register", "legal-register", "runtime-artifact-check"} <= jobs.keys()
    assert "prefect-register" not in jobs
    for name, kind in (("goods-register", "ingestion"), ("legal-register", "legal-information")):
        assert jobs[name]["spec"]["template"]["spec"]["containers"][0]["command"][-1] == kind
        feature = "specification_processing" if kind == "ingestion" else "legal_information"
        policy = yaml.safe_load((KUBE / "prefect" / (feature + ".yaml")).read_text())
        worker = workloads["prefect-worker" if kind == "ingestion" else "prefect-law-worker"]
        container = worker["spec"]["template"]["spec"]["containers"][0]
        assert container["command"][container["command"].index("--pool") + 1] == policy["pools"][0]["name"]
        for resource in (worker, jobs[name]):
            environment = next(e for e in resource["spec"]["template"]["spec"]["containers"][0]["env"] if e["name"] == "TEORIA_ENVIRONMENT")
            assert environment["valueFrom"]["configMapKeyRef"] == {
                "name": "teoria-mlops-connections", "key": "TEORIA_ENVIRONMENT",
            }
            endpoint = next(e for e in resource["spec"]["template"]["spec"]["containers"][0]["env"] if e["name"] == "PREFECT_API_URL")
            assert endpoint["valueFrom"]["configMapKeyRef"] == {
                "name": "teoria-mlops-connections", "key": "PREFECT_API_URL",
            }
    for resource in resources:
        if resource["kind"] in {"Deployment", "StatefulSet", "Job"}:
            for container in resource["spec"]["template"]["spec"]["containers"]:
                for entry in container.get("env", []):
                    assert not ("value" in entry and "valueFrom" in entry), entry
                    if entry["name"] == "TEORIA_ENVIRONMENT":
                        assert entry["valueFrom"]["configMapKeyRef"] == {
                            "name": "teoria-mlops-connections", "key": "TEORIA_ENVIRONMENT",
                        }


@pytest.mark.parametrize("overlay", ["generic", "k3s", "k3d"])
def test_platform_updates_exclude_foundation_servers_and_owner_provisioning(kubectl, overlay):
    resources = render(kubectl, overlay, "platform")
    workloads = {r["metadata"]["name"] for r in resources if r["kind"] in {"Deployment", "StatefulSet"}}
    assert {"admin-api", "runtime-api", "model-training-worker", "prefect-metadata-worker"} <= workloads
    assert not {"postgres", "platform-postgres", "minio", "prefect-server", "prefect-redis", "mlflow", "openmetadata-server"} & workloads
    jobs = {r["metadata"]["name"] for r in resources if r["kind"] == "Job"}
    assert "app-postgres-migrate" in jobs and "platform-databases-init" not in jobs
    assert "postgres-migrate" not in jobs  # Data schema upgrades are an explicit database operation.
    for resource in resources:
        if resource["kind"] in {"Deployment", "Job"}:
            for container in resource["spec"]["template"]["spec"]["containers"]:
                keys = {e.get("valueFrom", {}).get("secretKeyRef", {}).get("key") for e in container.get("env", [])}
                assert not {"TEORIA_LOCAL_PLATFORM_DB_PASSWORD", "TEORIA_MINIO_ROOT_PASSWORD"} & keys


def test_components_form_the_complete_deployment_without_duplicates(kubectl):
    seen = set()
    for component in ("database", "storage", "workflow", "mlflow", "openmetadata", "platform"):
        keys = {identity(r) for r in render(kubectl, component=component)}
        assert not keys & seen
        seen |= keys
    assert seen == {identity(r) for r in render(kubectl)}


def test_generic_storage_ingress_and_proxy_are_portable(kubectl):
    resources = render(kubectl, "generic", "all", "--storage-class", "cluster-csi", "--ingress-class", "public", "--cluster-domain", "corp.internal")
    for resource in resources:
        if resource["kind"] == "PersistentVolumeClaim":
            shared = resource["metadata"]["name"] in {"runtime-artifacts", "opa-signing-keys", "opa-bundles"}
            assert resource["spec"]["storageClassName"] == ("cluster-rwx" if shared else "cluster-csi")
        if resource["kind"] == "Ingress":
            assert resource["spec"]["ingressClassName"] == "public"
    ui = next(r for r in resources if r["kind"] == "Deployment" and r["metadata"]["name"] == "admin-ui")
    assert ui["spec"]["template"]["spec"]["containers"][0]["command"] == ["/bin/sh", "/etc/teoria_proxy/start.sh"]
    proxy = next(r for r in resources if r["kind"] == "ConfigMap" and "default.conf.template" in r.get("data", {}))
    assert "auth_request /_operations_auth" in proxy["data"]["default.conf.template"]
    assert "location /runtime-api/" in proxy["data"]["default.conf.template"]


@pytest.mark.parametrize("overlay,storage", [("k3s", "local-path"), ("k3d", "teoria-local")])
def test_local_environments_use_the_same_workloads_and_explicit_storage(kubectl, overlay, storage):
    resources = render(kubectl, overlay)
    assert all(r["spec"]["storageClassName"] == storage for r in resources if r["kind"] == "PersistentVolumeClaim")
    assert all(r["spec"]["ingressClassName"] == "traefik" for r in resources if r["kind"] == "Ingress")


def test_registry_is_external_and_jobs_use_the_selected_image_revision(kubectl):
    resources = render(kubectl, "k3d", "all", "--model-registry-host", "registry.example.com")
    assert not any(r["metadata"]["name"] in {"image-registry", "registry-data", "mlflow-auth"} for r in resources)
    api = next(r for r in resources if r["kind"] == "Deployment" and r["metadata"]["name"] == "admin-api")
    env = {e["name"]: e for e in api["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["TEORIA_IMAGE_REGISTRY_URL"]["value"] == "https://registry.example.com"
    for name in ("goods-register", "legal-register"):
        job = next(r for r in resources if r["kind"] == "Job" and r["metadata"]["name"] == name)
        env = {e["name"]: e for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
        image = "legal-job" if name == "legal-register" else "specification-job"
        assert env["TEORIA_PIPELINE_JOB_IMAGE"]["value"] == "ghcr.io/example/teoria/" + image + ":" + "a" * 40


@pytest.mark.parametrize("options", [["--features", "mlops"], ["--modules", "semantic"], ["--overlay", "unknown"],
    ["--storage-class", "bad;option"], ["--ingress-class", "https://invalid"], ["--cluster-domain", "invalid/domain"]])
def test_invalid_or_retired_options_fail_before_cluster_access(kubectl, options):
    result = subprocess.run(["bash", str(KUBE / "deploy.sh"), "registry.example.com/teoria", "a" * 40,
        "teoria.example.com", *options], env=kubectl, capture_output=True, text=True)
    assert result.returncode != 0
    assert "offline rendering attempted cluster access" not in result.stderr


def test_k3d_render_and_help_do_not_require_a_running_cluster(kubectl, tmp_path):
    result = subprocess.run(["bash", str(KUBE / "k3d/local.sh"), "render"],
        env={**kubectl, "TEORIA_K3D_REVISION": "a" * 40}, text=True, capture_output=True, check=True)
    resources = [r for r in yaml.safe_load_all(result.stdout) if r]
    assert any(r["kind"] == "Deployment" and r["metadata"]["name"] == "runtime-api" for r in resources)
    for script, option in [(KUBE / "deploy.sh", "--help"), (KUBE / "k3d/local.sh", "help")]:
        result = subprocess.run(["bash", str(script), option], env={**kubectl, "TEORIA_K3D_REVISION": ""}, capture_output=True, text=True)
        assert result.returncode == 0
        assert "deploy/README.md" in result.stdout


@pytest.mark.parametrize("domains_enabled", [False, True])
@pytest.mark.parametrize("component", ["platform", "all"])
def test_unified_lifecycle_orders_migrations_and_preserves_foundations(kubectl, tmp_path, component, domains_enabled):
    import json
    import sys
    wrapper = tmp_path / "kubectl"
    record = tmp_path / "calls.jsonl"
    wrapper.write_text(f"#!{sys.executable}\n" + r'''
import base64,json,os,sys
import yaml
args=sys.argv[1:]
if args[0]=='kustomize':
    os.execv(os.environ['TEORIA_TEST_REAL_KUBECTL'], [os.environ['TEORIA_TEST_REAL_KUBECTL'], *args])
stdin=sys.stdin.read() if args[-2:]==['-f','-'] else ''
objects=list(yaml.safe_load_all(stdin)) if stdin else []
with open(os.environ['TEORIA_TEST_CALL_RECORD'],'a') as f:
    f.write(json.dumps({'args':args,'objects':objects})+'\n')
if 'deployment/admin-api' in args and 'get' in args:
    pass  # A new installation.
elif 'get' in args and 'secret' in args and 'json' in args:
    keys=['TEORIA_LOCAL_PLATFORM_DB_PASSWORD','TEORIA_LOCAL_APP_DB_PASSWORD','TEORIA_LOCAL_PREFECT_DB_PASSWORD',
          'OPENMETADATA_DB_PASSWORD','TEORIA_MINIO_ROOT_USER','TEORIA_MINIO_ROOT_PASSWORD',
          'PREFECT_API_DATABASE_CONNECTION_URL','PREFECT_API_AUTH_STRING','TEORIA_ADMIN_API_TOKEN',
          'TEORIA_APP_DATABASE_URL','TEORIA_OPENMETADATA_AUTH_TOKEN','TEORIA_RUNTIME_API_TOKEN',
          'TEORIA_RUNTIME_DATA_DATABASE_URL','TEORIA_OPA_CONTROL_PLANE_TOKEN','TEORIA_MLFLOW_DB_PASSWORD',
          'MLFLOW_BACKEND_STORE_URI','TEORIA_MODEL_ALLOWED_REGISTRIES','TEORIA_MODEL_STORAGE_ACCESS_KEY','TEORIA_MODEL_STORAGE_SECRET_KEY','TEORIA_LOCAL_DATA_DB_PASSWORD','TEORIA_LOCAL_RUNTIME_DB_PASSWORD',
          'TEORIA_METADATA_DB_PASSWORD','TEORIA_PIPELINE_DATA_DATABASE_URL','TEORIA_CONNECTOR_MOLEG_LAW_API_KEY']
    data={k:base64.b64encode(b'synthetic-only').decode() for k in keys}
    feature={'TEORIA_SPECIFICATION_AUTHORING_API_URL':'http://admin-api.teoria.svc:8001',
        'TEORIA_SPECIFICATION_AUTHORING_API_TOKEN':'synthetic-workflow',
        'TEORIA_SPECIFICATION_ARTIFACT_ROOT':'s3://teoria-artifacts',
        'TEORIA_SPECIFICATION_S3_ENDPOINT':'http://minio.teoria.svc:9000',
        'TEORIA_SPECIFICATION_S3_ACCESS_KEY':'synthetic-access',
        'TEORIA_SPECIFICATION_S3_SECRET_KEY':'synthetic-secret'}
    source={'apiVersion':'v1','kind':'Secret','metadata':{'name':'specification-processing'},'type':'Opaque',
            'data':{k:base64.b64encode(v.encode()).decode() for k,v in feature.items()}}
    codex={'apiVersion':'v1','kind':'Secret','metadata':{'name':'specification-codex'},'type':'Opaque',
           'data':{'auth.json':base64.b64encode(b'{"OPENAI_API_KEY":"synthetic-model"}').decode()}}
    if 'specification-processing' in args and 'specification-codex' in args:
        print(json.dumps({'kind':'List','items':[source,codex]}))
    elif 'specification-processing' in args:print(json.dumps(source))
    elif 'specification-codex' in args or 'authoring-codex' in args:print(json.dumps(codex))
    else:print(json.dumps({'type':'Opaque','data':data}))
elif 'get' in args and 'configmap' in args and 'json' in args:
    print(json.dumps({'data':{'TEORIA_ENVIRONMENT':'production',**{key:'http://synthetic.example' for key in ('PREFECT_API_URL','TEORIA_MODEL_STORAGE_ENDPOINT','MLFLOW_TRACKING_URI','TEORIA_OPENMETADATA_BASE_URL')},'TEORIA_METADATA_SYNC_SCHEDULE_ENABLED':'false','TEORIA_SPECIFICATION_PROCESSING_ENABLED':os.environ['TEORIA_TEST_DOMAINS_ENABLED'],'TEORIA_LEGAL_INFORMATION_ENABLED':os.environ['TEORIA_TEST_DOMAINS_ENABLED']}}))
elif 'get' in args and 'job' in args:
    print('{"status":{"succeeded":1}}')
elif 'create' in args and 'namespace' in args:
    print(json.dumps({'apiVersion':'v1','kind':'Namespace','metadata':{'name':args[args.index('namespace')+1]}}))
else:
    print('{}')
''')
    wrapper.chmod(0o755)
    result = subprocess.run(["bash", str(KUBE / "deploy.sh"), "registry.example.com/teoria",
        "a" * 40, "teoria.example.com", "--overlay", "k3s",
        "--component", component], env={**kubectl, "TEORIA_TEST_CALL_RECORD": str(record), "TEORIA_TEST_DOMAINS_ENABLED": str(domains_enabled).lower()}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in record.read_text().splitlines()]
    objects = [item for call in calls for r in call["objects"] if r for item in (r["items"] if r["kind"] == "List" else [r])]
    applied = [(r["kind"], r["metadata"]["name"]) for r in objects]
    import re
    for name in ('admin-api','runtime-api','policy-control-plane','opa'):
        workload = next(r for r in objects if r['kind']=='Deployment' and r['metadata']['name']==name)
        revision = workload['spec']['template']['metadata']['annotations']['teoria.io/settings-revision']
        assert re.fullmatch(r'[a-f0-9]{64}', revision)
        assert 'synthetic-only' not in str(workload['spec']['template']['metadata']['annotations'])
    assert not any('create' in c['args'] and 'configmap' in c['args'] for c in calls)
    assert applied.index(("Job", "app-postgres-migrate")) < applied.index(("Deployment", "admin-api"))
    assert applied.index(("Job", "runtime-artifact-check")) < applied.index(("Deployment", "runtime-api"))
    assert applied.index(("Job", "metadata-register")) > applied.index(("Deployment", "admin-api"))
    assert applied.index(("Job", "model-register")) > applied.index(("Deployment", "admin-api"))
    foundations = {"platform-postgres", "prefect-server", "prefect-services", "prefect-redis", "minio", "mlflow", "openmetadata-server", "openmetadata-search"}
    applied_workloads = {name for kind, name in applied if kind in {"Deployment", "StatefulSet"}}
    assert foundations <= applied_workloads if component == "all" else not foundations & applied_workloads
    worker_objects = [r for r in objects if r["kind"] == "Deployment" and r["metadata"]["name"] in {"prefect-metadata-worker", "model-training-worker"}]
    assert all(r["spec"]["replicas"] == 0 for r in worker_objects)
    verification = next(i for i, call in enumerate(calls) if "teoria.entrypoints.deployment_check" in call["args"])
    assert all(i > verification for i, call in enumerate(calls) if "scale" in call["args"])
    assert not any("delete" in call["args"] and "job" not in call["args"] for call in calls)
    domain_secrets = [r for r in objects if r['kind'] == 'Secret' and r['metadata']['name'] in {'teoria-pipeline-secrets','teoria-legal-information-secrets'}]
    assert len(domain_secrets) == (2 if domains_enabled else 0)
    for secret in domain_secrets:
        assert set(secret['data']) <= {'TEORIA_PIPELINE_DATA_DATABASE_URL','PREFECT_API_AUTH_STRING','TEORIA_CONNECTOR_MOLEG_LAW_API_KEY'}
        assert 'TEORIA_ADMIN_API_TOKEN' not in secret['data']
    for name in ('prefect-worker','prefect-law-worker'):
        scale = next(call for call in calls if 'scale' in call['args'] and 'deployment/'+name in call['args'])
        assert '--replicas='+str(int(domains_enabled)) in scale['args']
    if component == "all":
        assert applied.index(("Job", "openmetadata-migrate")) < applied.index(("Deployment", "openmetadata-server"))




def test_deployment_images_are_built_by_ci_and_local_build():
    import re
    workflow = yaml.safe_load((ROOT / '.github/workflows/deploy_k3s.yaml').read_text())
    entries = workflow['jobs']['build']['strategy']['matrix']['include']
    published = {entry['name'] for entry in entries}
    ci_builds = {entry['name']: (entry['dockerfile'], entry.get('target', '-')) for entry in entries}
    assert len(ci_builds) == len(entries), 'Duplicate CI image name'
    local_script = (KUBE / 'k3d/local.sh').read_text()
    local_entries = re.findall(r"^      '([a-z-]+) ([^ ]+) ([^ ]+)'$", local_script, re.MULTILINE)
    local_builds = {name: (dockerfile, target) for name, dockerfile, target in local_entries}
    assert len(local_builds) == len(local_entries), 'Duplicate local image name'
    assert ci_builds == local_builds
    for entry in entries:
        dockerfile = ROOT / entry['dockerfile']
        assert dockerfile.is_file(), entry
        if target := entry.get('target'):
            assert re.search(r'^FROM .+ AS ' + re.escape(target) + r'$', dockerfile.read_text(), re.MULTILINE | re.IGNORECASE), entry
    required = set()
    for path in (KUBE / 'base').rglob('*.yaml'):
        for resource in yaml.safe_load_all(path.read_text()):
            if resource['kind'] not in {'Deployment', 'StatefulSet', 'Job'}:
                continue
            for container in resource['spec']['template']['spec']['containers']:
                image = container['image']
                if image.startswith('teoria/'):
                    required.add(image.removeprefix('teoria/').split(':')[0])
                for value in container.get('env', []):
                    reference = value.get('value', '')
                    if value['name'].endswith('_IMAGE') and reference.startswith('teoria/'):
                        required.add(reference.removeprefix('teoria/').split(':')[0])
    assert required | {'ingestion'} == published


@pytest.mark.parametrize('component', ['platform','all','mlflow'])
def test_missing_connections_fails_before_any_cluster_write(tmp_path, component):
    import json
    import sys
    wrapper=tmp_path/'kubectl'
    record=tmp_path/'calls.jsonl'
    wrapper.write_text(f'#!{sys.executable}\n'+'''
import json,os,sys
args=sys.argv[1:]
with open(os.environ['TEORIA_TEST_CONFIG_CALLS'],'a') as stream:stream.write(json.dumps(args)+'\\n')
if 'get' in args and 'configmap' in args:sys.exit(1)
if 'get' not in args:sys.exit('attempted a cluster mutation before checking connections')
print('{}')
''')
    wrapper.chmod(0o755)
    result=subprocess.run(['bash',str(KUBE/'deploy.sh'),'registry.example/teoria','a'*40,'teoria.example',
                           '--overlay','k3s','--component',component],capture_output=True,text=True,
        env={**os.environ,'PATH':str(tmp_path)+os.pathsep+os.environ['PATH'],'TEORIA_TEST_CONFIG_CALLS':str(record)})
    assert result.returncode != 0
    assert 'settings.sh apply' in result.stderr
    calls=[json.loads(line) for line in record.read_text().splitlines()]
    assert all('get' in args for args in calls)
    assert not any('create' in args or 'apply' in args or 'delete' in args for args in calls)


def test_mlflow_uses_settings_revision_without_requiring_enabled_domain_secrets(kubectl, tmp_path):
    import json
    import sys
    wrapper=tmp_path/'kubectl'
    record=tmp_path/'calls.jsonl'
    wrapper.write_text(f'#!{sys.executable}\n'+'''
import base64,json,os,sys,yaml
args=sys.argv[1:]
if args[0]=='kustomize':os.execv(os.environ['TEORIA_TEST_REAL_KUBECTL'],[os.environ['TEORIA_TEST_REAL_KUBECTL'],*args])
body=sys.stdin.read() if args[-2:]==['-f','-'] else ''
objects=list(yaml.safe_load_all(body)) if body else []
with open(os.environ['TEORIA_TEST_CONFIG_CALLS'],'a') as stream:stream.write(json.dumps({'args':args,'objects':objects})+'\\n')
if 'get' in args and 'configmap' in args:
    print(json.dumps({'data':{'TEORIA_MODEL_STORAGE_ENDPOINT':'http://minio:9000','TEORIA_SPECIFICATION_PROCESSING_ENABLED':os.environ.get('TEORIA_TEST_DOMAIN_FLAG','true')}}))
elif 'get' in args and 'secret' in args and 'json' in args:
    if 'specification-processing' in args:sys.exit('unrelated domain Secret requested')
    print(json.dumps({'metadata':{'uid':'synthetic-id','resourceVersion':'1'},'data':{key:base64.b64encode(b'synthetic-only').decode() for key in ['TEORIA_MINIO_ROOT_USER','TEORIA_MINIO_ROOT_PASSWORD','MLFLOW_BACKEND_STORE_URI']}}))
elif 'create' in args and 'namespace' in args:
    print(json.dumps({'apiVersion':'v1','kind':'Namespace','metadata':{'name':'teoria'}}))
else:print('{}')
''')
    wrapper.chmod(0o755)
    for domain_flag in ('true','false'):
        result=subprocess.run(['bash',str(KUBE/'deploy.sh'),'registry.example/teoria','a'*40,'teoria.example',
                               '--overlay','k3s','--component','mlflow'],capture_output=True,text=True,
            env={**kubectl,'TEORIA_TEST_CONFIG_CALLS':str(record),'TEORIA_TEST_DOMAIN_FLAG':domain_flag})
        assert result.returncode == 0, result.stderr
    calls=[json.loads(line) for line in record.read_text().splitlines()]
    workloads=[r for call in calls for r in call['objects'] if r and r['kind']=='Deployment' and r['metadata']['name']=='mlflow']
    assert len(workloads) == 2
    revisions={r['spec']['template']['metadata']['annotations']['teoria.io/settings-revision'] for r in workloads}
    assert len(revisions) == 1  # An unrelated domain activation change must not restart MLflow.
    assert len(revisions.pop()) == 64
    assert not any('create' in call['args'] and 'configmap' in call['args'] for call in calls)
