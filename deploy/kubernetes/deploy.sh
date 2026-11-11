#!/usr/bin/env bash
# Kubernetes deployment through the caller's kubectl context; no SSH or provider API is required.
set -Eeuo pipefail
image_prefix=${1:?image registry prefix required}
revision=${2:?commit SHA required}
public_host=${3:?public DNS name required}
model_registry_host=
modules=semantic
overlay=generic
storage_class=
shared_storage_class=
ingress_class=
cluster_domain=cluster.local
render_only=false
shift 3
while (( $# )); do
  case "$1" in
    --with-model-registry) model_registry_host=${2:?Registry hostname required}; shift 2 ;;
    --modules) modules=${2:?modules required}; shift 2 ;;
    --overlay) overlay=${2:?overlay required}; shift 2 ;;
    --storage-class) storage_class=${2:?StorageClass required}; shift 2 ;;
    --shared-storage-class) shared_storage_class=${2:?RWX StorageClass required}; shift 2 ;;
    --ingress-class) ingress_class=${2:?IngressClass required}; shift 2 ;;
    --cluster-domain) cluster_domain=${2:?cluster DNS domain required}; shift 2 ;;
    --render) render_only=true; shift ;;
    *) echo "Unknown deployment option: $1" >&2; exit 1 ;;
  esac
done
[[ "$modules" == semantic || "$modules" == mlops ]] || { echo 'Kubernetes currently supports --modules semantic or mlops' >&2; exit 1; }
[[ "$overlay" == k3s || "$overlay" == generic ]] || { echo 'Choose --overlay k3s or generic' >&2; exit 1; }
for value in "$storage_class" "$shared_storage_class" "$ingress_class" "$cluster_domain"; do
  [[ -z "$value" || "$value" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || { echo 'Invalid Kubernetes class or DNS domain' >&2; exit 1; }
done
if [[ "$overlay" == generic && "$modules" == semantic && -z "$shared_storage_class" ]]; then
  echo 'Generic Semantic deployment requires --shared-storage-class with ReadWriteMany support for shared artifacts.' >&2
  exit 1
fi
if [[ -n "$model_registry_host" ]]; then
  [[ "$model_registry_host" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || { echo 'Invalid model Registry hostname' >&2; exit 1; }
fi
[[ "$modules" != mlops || -n "$model_registry_host" ]] || { echo 'MLOps requires --with-model-registry HOST' >&2; exit 1; }
[[ "$revision" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid commit SHA' >&2; exit 1; }
[[ "$image_prefix" =~ ^[a-z0-9][a-z0-9.-]*(:[0-9]+)?/[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*$ ]] || { echo 'Invalid image registry prefix (hostname[:port]/namespace required)' >&2; exit 1; }
[[ "$public_host" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || { echo 'Invalid public hostname' >&2; exit 1; }
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
command -v kubectl >/dev/null
command -v python3 >/dev/null
# Also serialize manual deploys; offline rendering never acquires a deployment lock.
if [[ "$render_only" != true ]]; then
  exec 9>"${HOME}/.teoria-deploy.lock"
  flock -w 1200 9
fi
scratch=$(mktemp -d "$root/.release_XXXXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
trap 'echo "Deployment failed; existing PVCs and release files are retained. Check Kubernetes Job/Pod status." >&2' ERR
render() {
  python3 - "$root" "$scratch" "$1" "$image_prefix" "$revision" "$public_host" "$model_registry_host" "$overlay" "$storage_class" "$ingress_class" "$cluster_domain" "$shared_storage_class" <<'PY'
import json,os,sys
root,out,resource,prefix,revision,host,registry_host,overlay,storage_class,ingress_class,cluster_domain,shared_storage_class=sys.argv[1:]
selected=root+'/overlays/'+overlay+'/'+resource
resource_path=selected if os.path.isdir(selected) else root+'/base/'+resource
images=['runtime','authoring','admin-ui','pipelines','metadata-worker','opa','opa-builder','ingestion','admin','mlflow','model-dispatcher']
config={'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization',
        'namespace':'teoria-pipelines' if resource=='execution' else 'teoria',
        'resources':[os.path.relpath(resource_path,out)],
        'images':[{'name':'teoria/'+name,'newName':prefix+'/'+name,'newTag':revision} for name in images]}
def patch(kind,name,body):
    config.setdefault('patches',[]).append({'target':{'kind':kind,'name':name},'patch':json.dumps(body)})
if resource=='mlops':
    patch('Ingress','image-registry',[
        {'op':'replace','path':'/spec/rules/0/host','value':registry_host},
        {'op':'replace','path':'/spec/tls/0/hosts/0','value':registry_host}])
if resource in {'application', 'mlops/base'}:
    for ingress in (('teoria',) if overlay=='generic' else ('teoria', 'teoria-api') + (('teoria-mlflow',) if resource=='mlops/base' else ())):
        patch('Ingress',ingress,[
            {'op':'replace','path':'/spec/rules/0/host','value':host},
            {'op':'replace','path':'/spec/tls/0/hosts/0','value':host}])
    if resource=='mlops/base':
        patch('Deployment','admin-api',{'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'admin-api'},
            'spec':{'template':{'spec':{'containers':[{'name':'admin-api','env':[
                {'name':'TEORIA_IMAGE_REGISTRY_PUBLIC_HOST','value':registry_host}]}]}}}})
        patch('Deployment','mlflow',{'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'mlflow'},
            'spec':{'template':{'spec':{'containers':[{'name':'mlflow','env':[
                {'name':'MLFLOW_SERVER_ALLOWED_HOSTS','value':'mlflow:5000,mlflow,localhost:5000,127.0.0.1:5000,'+host}]}]}}}})
    # Kubernetes image transforms do not touch environment variables.
    if resource=='application':
        patch('Deployment','prefect-metadata-worker',{
        'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'prefect-metadata-worker'},
        'spec':{'template':{'spec':{'containers':[{'name':'prefect-metadata-worker','env':[
            {'name':'TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE','value':prefix+'/ingestion:'+revision}]}]}}}})
if storage_class:
    patch('PersistentVolumeClaim','.*',[{'op':'add','path':'/spec/storageClassName','value':storage_class}])
if shared_storage_class:
    for name in ('runtime-artifacts', 'opa-signing-keys', 'opa-bundles'):
        patch('PersistentVolumeClaim',name,[
            {'op':'add','path':'/spec/storageClassName','value':shared_storage_class},
            {'op':'replace','path':'/spec/accessModes','value':['ReadWriteMany']}])
if ingress_class:
    patch('Ingress','.*',[{'op':'add','path':'/spec/ingressClassName','value':ingress_class}])
if overlay=='generic' and resource in {'application','mlops/base'}:
    patch('Deployment','admin-ui',{'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'admin-ui'},
        'spec':{'template':{'spec':{'containers':[{'name':'admin-ui','env':[
            {'name':'TEORIA_CLUSTER_DOMAIN','value':cluster_domain}]}]}}}})
if resource=='jobs/prefect-register.yaml':
    patch('Job','prefect-register',{'apiVersion':'batch/v1','kind':'Job','metadata':{'name':'prefect-register'},
        'spec':{'template':{'spec':{'containers':[{'name':'prefect-register','env':[
            {'name':'TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE','value':prefix+'/ingestion:'+revision},
            {'name':'TEORIA_PIPELINE_JOB_IMAGE','value':prefix+'/pipelines:'+revision}]}]}}}})
if resource=='jobs/opa-bundle-build.yaml':
    patch('Job','opa-bundle-build',{'apiVersion':'batch/v1','kind':'Job','metadata':{'name':'opa-bundle-build'},
        'spec':{'template':{'spec':{'containers':[{'name':'opa-bundle-build','env':[
            {'name':'TEORIA_OPA_BUNDLE_REVISION','value':revision}]}]}}}})
with open(out+'/kustomization.yaml','w') as f:json.dump(config,f)
PY
  kubectl kustomize --load-restrictor LoadRestrictionsNone "$scratch"
}
run_job() {
  local name=$1
  kubectl -n teoria delete job "$name" --ignore-not-found --wait=true >/dev/null
  render "jobs/$name.yaml" | kubectl apply -f -
  local deadline=$((SECONDS + 1200)) state
  while (( SECONDS < deadline )); do
    state=$(kubectl -n teoria get job "$name" -o json | python3 -c 'import json,sys; s=json.load(sys.stdin).get("status",{}); print("complete" if s.get("succeeded") else "failed" if s.get("failed") else "pending")')
    if [[ "$state" == complete ]]; then return; fi
    if [[ "$state" == failed ]]; then echo "Job $name failed; inspect its Pod logs in the selected cluster." >&2; return 1; fi
    sleep 3
  done
  echo "Timed out waiting for Job $name" >&2
  return 1
}
if [[ "$render_only" == true ]]; then
  phases=(execution infrastructure openmetadata application)
  jobs=(postgres-init platform-postgres-init postgres-migrate postgres-metadata-grants app-postgres-migrate openmetadata-migrate opa-bundle-build runtime-artifact-check prefect-register)
  if [[ "$modules" == mlops ]]; then
    phases=(mlops mlops/base)
    jobs=(mlops-postgres-init app-postgres-migrate model-storage-init model-register)
    kubectl kustomize "$root/base/mlops/execution"
    printf '\n---\n'
  elif [[ -n "$model_registry_host" ]]; then
    phases+=(mlops)
  fi
  for phase in "${phases[@]}"; do render "$phase"; printf '\n---\n'; done
  for job in "${jobs[@]}"; do render "jobs/$job.yaml"; printf '\n---\n'; done
  exit 0
fi
kubectl get nodes >/dev/null
kubectl create namespace teoria --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace teoria-pipelines --dry-run=client -o yaml | kubectl apply -f -
for secret in teoria-secrets teoria-registry teoria-tls; do
  kubectl -n teoria get secret "$secret" >/dev/null || {
    echo "Create Kubernetes Secret $secret according to docs/deployment/kubernetes.md" >&2; exit 1;
  }
done
if [[ -n "$model_registry_host" ]]; then
  for secret in model-registry-auth; do
    kubectl -n teoria get secret "$secret" >/dev/null || {
      echo "Create Kubernetes Secret $secret according to docs/deployment/image_registry.md" >&2; exit 1;
    }
  done
fi
if [[ "$overlay" == k3s ]]; then
  kubectl get crd middlewares.traefik.io >/dev/null
fi
if [[ -n "$ingress_class" ]]; then kubectl get ingressclass "$ingress_class" >/dev/null; fi
if [[ -n "$storage_class" ]]; then kubectl get storageclass "$storage_class" >/dev/null; fi
if [[ -n "$shared_storage_class" ]]; then kubectl get storageclass "$shared_storage_class" >/dev/null; fi
if [[ "$modules" == mlops ]]; then
  # Refuse an implicit switch that would leave incompatible semantic workloads running.
  existing_runtime=$(kubectl -n teoria get deployment/runtime-api --ignore-not-found -o name)
  if [[ -n "$existing_runtime" ]]; then
    echo 'Use a separate namespace/cluster or explicitly retire the semantic installation before selecting MLOps.' >&2
    exit 1
  fi
  for secret in model-control; do kubectl -n teoria get secret "$secret" >/dev/null; done
  kubectl -n teoria-models get secret model-images >/dev/null
  kubectl -n teoria-models get secret model-workload >/dev/null
  kubectl -n teoria get secret teoria-secrets -o json | python3 -c '
import base64,json,sys
v={k:base64.b64decode(x).decode() for k,x in json.load(sys.stdin)["data"].items()}
keys=["TEORIA_LOCAL_PLATFORM_DB_PASSWORD","TEORIA_LOCAL_APP_DB_PASSWORD","TEORIA_LOCAL_PREFECT_DB_PASSWORD","TEORIA_ADMIN_API_TOKEN","TEORIA_APP_DATABASE_URL","PREFECT_API_DATABASE_CONNECTION_URL","PREFECT_API_AUTH_STRING","TEORIA_MINIO_ROOT_USER","TEORIA_MINIO_ROOT_PASSWORD"]
assert all(v.get(k) and "CHANGE_ME" not in v[k] for k in keys), "Configure MLOps Secret keys"
'
  if [[ "$overlay" == k3s ]]; then
  # Traefik Basic auth consumes the same bcrypt file as the model Registry.
  kubectl -n teoria get secret model-registry-auth -o json | python3 -c '
import json,sys
source=json.load(sys.stdin)["data"]["htpasswd"]
json.dump({"apiVersion":"v1","kind":"Secret","metadata":{"name":"model-ui-auth","namespace":"teoria"},"type":"Opaque","data":{"users":source}},sys.stdout)
' | kubectl apply -f -
  fi
  kubectl kustomize "$root/base/mlops/execution" | kubectl apply -f -
  render mlops | kubectl apply -f -
  render mlops/base | kubectl apply -f -
  for stateful in platform-postgres prefect-redis; do
    kubectl -n teoria rollout status "statefulset/$stateful" --timeout=600s
  done
  run_job mlops-postgres-init
  run_job app-postgres-migrate
  kubectl -n teoria rollout status deployment/minio --timeout=600s
  run_job model-storage-init
  for service in image-registry mlflow prefect-server prefect-services admin-api admin-ui; do
    kubectl -n teoria rollout status "deployment/$service" --timeout=600s
  done
  run_job model-register
  kubectl -n teoria rollout status deployment/model-training-worker --timeout=600s
  kubectl -n teoria exec deployment/admin-api -- python -m teoria.entrypoints.deployment_check '{"mlops":true,"semantic":false,"formatid":false}'
  printf 'MLOps manifests deployed; verify public TLS and a real training/serving run at https://%s\n' "$public_host"
  exit 0
fi
# Reject example credentials before starting any database or application workload.
kubectl -n teoria get secret teoria-secrets -o json | python3 -c '
import base64,json,sys
values={k:base64.b64decode(v).decode() for k,v in json.load(sys.stdin)["data"].items()}
required=["TEORIA_LOCAL_DATA_DB_PASSWORD","TEORIA_LOCAL_PLATFORM_DB_PASSWORD","TEORIA_LOCAL_APP_DB_PASSWORD","TEORIA_LOCAL_PREFECT_DB_PASSWORD","TEORIA_LOCAL_RUNTIME_DB_PASSWORD","TEORIA_METADATA_DB_PASSWORD","OPENMETADATA_DB_PASSWORD","TEORIA_ADMIN_API_TOKEN","TEORIA_RUNTIME_API_TOKEN","TEORIA_OPA_CONTROL_PLANE_TOKEN","TEORIA_APP_DATABASE_URL","TEORIA_PIPELINE_DATA_DATABASE_URL","TEORIA_RUNTIME_DATA_DATABASE_URL","PREFECT_API_DATABASE_CONNECTION_URL","PREFECT_API_AUTH_STRING","TEORIA_CONNECTOR_MOLEG_LAW_API_KEY"]
invalid=[k for k in required if not values.get(k) or "CHANGE_ME" in values[k]]
if invalid: print("Configure Kubernetes Secret keys: "+", ".join(invalid),file=sys.stderr); sys.exit(1)
'
# Job Pods receive only ingestion credentials, never Admin or database-owner keys.
kubectl -n teoria get secret teoria-secrets -o json | python3 -c '
import json,sys
source=json.load(sys.stdin)["data"]
keys=["TEORIA_PIPELINE_DATA_DATABASE_URL","PREFECT_API_AUTH_STRING"]
def secret(name, selected):
    return {"apiVersion":"v1","kind":"Secret","metadata":{"name":name,"namespace":"teoria-pipelines"},"type":"Opaque","data":{k:source[k] for k in selected}}
json.dump({"apiVersion":"v1","kind":"List","items":[secret("teoria-pipeline-secrets", keys),secret("teoria-legal-information-secrets", keys+["TEORIA_CONNECTOR_MOLEG_LAW_API_KEY"])]},sys.stdout)
' | kubectl apply -f -
kubectl -n teoria get secret teoria-registry -o json | python3 -c '
import json,sys
source=json.load(sys.stdin)
json.dump({"apiVersion":"v1","kind":"Secret","metadata":{"name":"teoria-registry","namespace":"teoria-pipelines"},"type":source["type"],"data":source["data"]},sys.stdout)
' | kubectl apply -f -
if [[ -n "$model_registry_host" ]]; then
  render mlops | kubectl apply -f -
  kubectl -n teoria rollout status deployment/image-registry --timeout=600s
fi
render execution | kubectl apply -f -
render infrastructure | kubectl apply -f -
for service in postgres platform-postgres prefect-redis openmetadata-search; do
  kubectl -n teoria rollout status "statefulset/$service" --timeout=600s
done
for job in postgres-init platform-postgres-init postgres-migrate postgres-metadata-grants app-postgres-migrate openmetadata-migrate opa-bundle-build; do
  run_job "$job"
done
render openmetadata | kubectl apply -f -
kubectl -n teoria rollout status deployment/openmetadata-server --timeout=600s
# Approval and publication are separate from deploying application code.
run_job runtime-artifact-check
render application | kubectl apply -f -
for service in policy-control-plane opa runtime-api admin-api admin-ui prefect-server prefect-services; do
  kubectl -n teoria rollout status "deployment/$service" --timeout=600s
done
run_job prefect-register
for service in prefect-worker prefect-metadata-worker; do
  kubectl -n teoria rollout status "deployment/$service" --timeout=600s
done
# Verify the public ingress before removing the retired edge proxy.
kubectl -n teoria exec -i deployment/admin-api -- python - "$public_host" <<'PYTHON'
import json,os,sys,urllib.request
base="https://"+sys.argv[1]
headers={"Authorization":"Bearer "+os.environ["TEORIA_ADMIN_API_TOKEN"]}
for path in ("/", "/health", "/prefect/"):
    assert urllib.request.urlopen(base+path,timeout=30).status==200, path
for path in ("/admin-api/v1/admin/auth/session", "/admin-api/v1/admin/metadata/status"):
    request=urllib.request.Request(base+path,headers=headers)
    response=urllib.request.urlopen(request,timeout=30)
    assert response.status==200, path
    if path.endswith("/metadata/status"):
        assert json.load(response)["available"]
request=urllib.request.Request(base+"/runtime-api/v1/version",headers={"Authorization":"Bearer "+os.environ["TEORIA_CONTEXT_RUNTIME_API_TOKEN"]})
version=json.load(urllib.request.urlopen(request,timeout=30))
assert version["runtime_artifact"]["bundle_checksum"]
print("Public UI, health, Prefect, authenticated APIs and Runtime artifact verified")
PYTHON
kubectl -n teoria delete deployment/nginx service/nginx --ignore-not-found=true
printf 'Deployed commit %s to https://%s\n' "$revision" "$public_host"
