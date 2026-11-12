#!/usr/bin/env bash
# Deploy one Teoria platform through the caller's kubectl context.
set -Eeuo pipefail
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
  cat <<'HELP'
Usage: bash deploy/kubernetes/deploy.sh IMAGE_PREFIX COMMIT_SHA PUBLIC_HOST [options]

Teoria runs Metadata, Ontology and MLOps together.
  --component platform|database|storage|workflow|mlflow|openmetadata|all
                                        Deployment scope (default: platform)
  --overlay generic|k3s|k3d              Cluster environment (default: generic)
  --render                              Print YAML without cluster access
  --model-registry-host HOST[:PORT]      External model image Registry
  --model-registry-url https://HOST      Registry API origin
  --storage-class NAME                  Dedicated PVC class
  --shared-storage-class NAME           RWX storage for generic Runtime artifacts
  --ingress-class NAME                  Installed IngressClass
  --cluster-domain NAME                 DNS suffix (default: cluster.local)

Default deployment updates Teoria, not its foundation services.
Domain activation and schedules use the operational ConfigMap.
Start here: deploy/README.md
HELP
  exit 0
fi
image_prefix=${1:?image registry prefix required}
revision=${2:?commit SHA required}
public_host=${3:?public DNS name required}
model_registry_host=
model_registry_url=
component=platform
overlay=generic
storage_class=
shared_storage_class=
ingress_class=
cluster_domain=cluster.local
render_only=false
pause_workers=false
shift 3
while (( $# )); do
  case "$1" in
    --model-registry-host) model_registry_host=${2:?Registry host required}; shift 2 ;;
    --model-registry-url) model_registry_url=${2:?Registry origin required}; shift 2 ;;
    --component) component=${2:?component required}; shift 2 ;;
    --overlay) overlay=${2:?overlay required}; shift 2 ;;
    --storage-class) storage_class=${2:?StorageClass required}; shift 2 ;;
    --shared-storage-class) shared_storage_class=${2:?RWX StorageClass required}; shift 2 ;;
    --ingress-class) ingress_class=${2:?IngressClass required}; shift 2 ;;
    --cluster-domain) cluster_domain=${2:?cluster DNS domain required}; shift 2 ;;
    --render) render_only=true; shift ;;
    --features|--modules) echo 'Teoria is deployed together; omit --features and --modules.' >&2; exit 1 ;;
    *) echo "Unknown deployment option: $1" >&2; exit 1 ;;
  esac
done
case "$component" in platform|database|storage|workflow|mlflow|openmetadata|all) ;; *) echo 'Invalid deployment component' >&2; exit 1 ;; esac
[[ "$overlay" == k3s || "$overlay" == k3d || "$overlay" == generic ]] || { echo 'Choose --overlay k3s, k3d or generic' >&2; exit 1; }
if [[ "$overlay" == k3d ]]; then
  storage_class=${storage_class:-teoria-local}
  model_registry_host=${model_registry_host:-harbor.teoria.localhost}
  model_registry_url=${model_registry_url:-https://$model_registry_host}
elif [[ "$overlay" == k3s ]]; then storage_class=${storage_class:-local-path}; fi
if [[ "$overlay" != generic ]]; then ingress_class=${ingress_class:-traefik}; fi
for value in "$storage_class" "$shared_storage_class" "$ingress_class" "$cluster_domain"; do
  [[ -z "$value" || "$value" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || { echo 'Invalid Kubernetes class or DNS domain' >&2; exit 1; }
done
if [[ "$overlay" == generic && ( "$component" == platform || "$component" == all ) && -z "$shared_storage_class" ]]; then
  echo 'Generic Teoria deployment requires --shared-storage-class with ReadWriteMany support.' >&2; exit 1
fi
if [[ -n "$model_registry_host" || -n "$model_registry_url" ]]; then
  python3 - "$model_registry_host" "$model_registry_url" <<'PYREGISTRY'
import re,sys
from urllib.parse import urlsplit
host,origin=sys.argv[1:]
if not re.fullmatch(r'[a-z0-9]([a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?',host):
    sys.exit('Invalid model Registry host')
parsed=urlsplit(origin or 'https://'+host)
try:
    valid=parsed.scheme in {'http','https'} and parsed.hostname and parsed.port != 0
except ValueError:
    valid=False
if not valid or parsed.username or parsed.password or parsed.path not in {'','/'} or parsed.query or parsed.fragment:
    sys.exit('Invalid model Registry origin')
PYREGISTRY
  model_registry_url=${model_registry_url:-https://$model_registry_host}
fi
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
  python3 - "$root" "$scratch" "$1" "$image_prefix" "$revision" "$public_host" "$model_registry_host" "$model_registry_url" "$overlay" "$storage_class" "$ingress_class" "$cluster_domain" "$shared_storage_class" "$pause_workers" <<'PY'
import json,os,sys
root,out,resource,prefix,revision,host,registry_host,registry_url,overlay,storage_class,ingress_class,cluster_domain,shared_storage_class,pause_workers=sys.argv[1:]
resource_path=root+'/overlays/'+overlay if resource=='teoria' else root+'/base/'+resource
images=['runtime','authoring','admin-ui','pipelines','metadata-worker','opa','opa-builder','ingestion','admin','mlflow','model-dispatcher','specification-job','legal-job']
config={'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization',
    'namespace':'teoria-pipelines' if resource=='teoria/pipeline_execution' else 'teoria',
    'resources':[os.path.relpath(resource_path,out)],
    'images':[{'name':'teoria/'+name,'newName':prefix+'/'+name,'newTag':revision} for name in images]}
def patch(kind,name,body):
    config.setdefault('patches',[]).append({'target':{'kind':kind,'name':name},'patch':json.dumps(body)})
def environment(kind,name,values):
    patch(kind,name,{'apiVersion':'batch/v1' if kind=='Job' else 'apps/v1','kind':kind,'metadata':{'name':name},
        'spec':{'template':{'spec':{'containers':[{'name':name,'env':values}]}}}})
if resource=='teoria':
    patch('Ingress','teoria',[{'op':'replace','path':'/spec/rules/0/host','value':host},
        {'op':'replace','path':'/spec/tls/0/hosts/0','value':host}])
    environment('Deployment','admin-ui',[{'name':'TEORIA_CLUSTER_DOMAIN','value':cluster_domain}])
    if registry_host:
        environment('Deployment','admin-api',[
            {'name':'TEORIA_IMAGE_REGISTRY_PUBLIC_HOST','value':registry_host,'valueFrom':None},
            {'name':'TEORIA_IMAGE_REGISTRY_URL','value':registry_url,'valueFrom':None}])
    environment('Deployment','prefect-metadata-worker',[
        {'name':'TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE','value':prefix+'/ingestion:'+revision}])
    if pause_workers=='true':
        for name in ('prefect-metadata-worker','model-training-worker','prefect-worker','prefect-law-worker'):
            patch('Deployment',name,{'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':name},'spec':{'replicas':0}})
if resource=='services/mlflow':
    environment('Deployment','mlflow',[{'name':'MLFLOW_SERVER_ALLOWED_HOSTS','value':
        'mlflow:5000,mlflow,mlflow.teoria.svc:5000,mlflow.teoria.svc.'+cluster_domain+':5000,localhost:5000,127.0.0.1:5000,'+host}])
if storage_class:
    patch('PersistentVolumeClaim','.*',[{'op':'add','path':'/spec/storageClassName','value':storage_class}])
if shared_storage_class:
    for name in ('runtime-artifacts','opa-signing-keys','opa-bundles'):
        patch('PersistentVolumeClaim',name,[{'op':'add','path':'/spec/storageClassName','value':shared_storage_class},
            {'op':'replace','path':'/spec/accessModes','value':['ReadWriteMany']}])
if ingress_class:patch('Ingress','.*',[{'op':'add','path':'/spec/ingressClassName','value':ingress_class}])
if resource in {'teoria/metadata_register.yaml','domains/goods/register.yaml','domains/legal_information/register.yaml'}:
    name={'teoria/metadata_register.yaml':'metadata-register','domains/goods/register.yaml':'goods-register',
          'domains/legal_information/register.yaml':'legal-register'}[resource]
    environment('Job',name,[{'name':'TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE','value':prefix+'/ingestion:'+revision}])
    if name!='metadata-register':
        environment('Job',name,[{'name':'TEORIA_PIPELINE_JOB_IMAGE','value':prefix+('/legal-job:' if name=='legal-register' else '/specification-job:')+revision}])
if resource=='teoria/build_policy.yaml':
    environment('Job','opa-bundle-build',[{'name':'TEORIA_OPA_BUNDLE_REVISION','value':revision}])
with open(out+'/kustomization.yaml','w') as f:json.dump(config,f)
PY
  kubectl kustomize --load-restrictor LoadRestrictionsNone "$scratch"
}
component_resource() {
  case "$1" in
    database) echo services/postgres ;; storage) echo services/minio ;; workflow) echo services/prefect ;;
    mlflow) echo services/mlflow ;; openmetadata) echo services/openmetadata ;; platform) echo teoria ;;
  esac
}
job_resource() {
  case "$1" in
    platform-databases-init) echo services/postgres/initialize_platform.yaml ;;
    postgres-init) echo services/postgres/initialize_data.yaml ;;
    postgres-migrate) echo teoria/migrate_data.yaml ;;
    postgres-metadata-grants) echo services/postgres/grant_metadata_read.yaml ;;
    app-postgres-migrate) echo teoria/migrate_application.yaml ;;
    opa-bundle-build) echo teoria/build_policy.yaml ;;
    runtime-artifact-check) echo teoria/verify_runtime_artifact.yaml ;;
    model-storage-init) echo services/minio/initialize_mlops.yaml ;;
    openmetadata-migrate) echo services/openmetadata/migrate.yaml ;;
    metadata-register) echo teoria/metadata_register.yaml ;;
    model-register) echo teoria/model_register.yaml ;;
    goods-register) echo domains/goods/register.yaml ;;
    legal-register) echo domains/legal_information/register.yaml ;;
    *) echo "Unknown deployment Job: $1" >&2; return 1 ;;
  esac
}
component_jobs() {
  case "$1" in
    database) echo 'platform-databases-init postgres-init postgres-migrate postgres-metadata-grants' ;;
    storage) echo model-storage-init ;; openmetadata) echo openmetadata-migrate ;;
    platform) echo 'app-postgres-migrate opa-bundle-build runtime-artifact-check metadata-register model-register goods-register legal-register' ;;
  esac
}
run_job() {
  local name=$1
  kubectl -n teoria delete job "$name" --ignore-not-found --wait=true >/dev/null
  render "$(job_resource "$name")" | kubectl apply -f -
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
components=("$component")
[[ "$component" != all ]] || components=(database storage workflow mlflow openmetadata platform)
if [[ "$render_only" == true ]]; then
  for selected in "${components[@]}"; do
    if [[ "$selected" == platform ]]; then
      render teoria/pipeline_execution; printf '\n---\n'
      kubectl kustomize "$root/base/teoria/model_execution"; printf '\n---\n'
    fi
    if [[ "$selected" == openmetadata ]]; then render services/openmetadata/search.yaml; printf '\n---\n'; fi
    render "$(component_resource "$selected")"; printf '\n---\n'
    for job in $(component_jobs "$selected"); do render "$(job_resource "$job")"; printf '\n---\n'; done
  done
  exit 0
fi
# Validate selected lifecycle credentials before updating any workload.
kubectl get nodes >/dev/null
if [[ "$overlay" == k3d ]]; then
  kubectl get nodes -o json | python3 -c 'import json,sys; sys.exit(0 if len(json.load(sys.stdin)["items"])==1 else "The k3d overlay requires one node")'
fi
kubectl create namespace teoria --dry-run=client -o yaml | kubectl apply -f -
required_secrets=(teoria-secrets teoria-registry)
case "$component" in platform|all) required_secrets+=(teoria-tls model-control) ;; database|mlflow) required_secrets+=(model-control) ;; esac
for secret in "${required_secrets[@]}"; do kubectl -n teoria get secret "$secret" >/dev/null; done
for kind in storageclass ingressclass; do
  values=("$ingress_class")
  [[ "$kind" != storageclass ]] || values=("$storage_class" "$shared_storage_class")
  for value in "${values[@]}"; do [[ -z "$value" ]] || kubectl get "$kind" "$value" >/dev/null; done
done
kubectl -n teoria get secret teoria-secrets -o json | python3 -c '
import base64,json,sys
values={k:base64.b64decode(v).decode() for k,v in json.load(sys.stdin)["data"].items()}
required={
"database":["TEORIA_LOCAL_PLATFORM_DB_PASSWORD","TEORIA_LOCAL_APP_DB_PASSWORD","TEORIA_LOCAL_PREFECT_DB_PASSWORD","OPENMETADATA_DB_PASSWORD","TEORIA_LOCAL_DATA_DB_PASSWORD","TEORIA_LOCAL_RUNTIME_DB_PASSWORD","TEORIA_METADATA_DB_PASSWORD","TEORIA_PIPELINE_DATA_DATABASE_URL"],
"storage":["TEORIA_MINIO_ROOT_USER","TEORIA_MINIO_ROOT_PASSWORD"],
"workflow":["PREFECT_API_DATABASE_CONNECTION_URL","PREFECT_API_AUTH_STRING"],
"mlflow":["TEORIA_MINIO_ROOT_USER","TEORIA_MINIO_ROOT_PASSWORD"],
"openmetadata":["OPENMETADATA_DB_PASSWORD"],
"platform":["TEORIA_ADMIN_API_TOKEN","TEORIA_APP_DATABASE_URL","PREFECT_API_AUTH_STRING","TEORIA_OPENMETADATA_AUTH_TOKEN","TEORIA_RUNTIME_API_TOKEN","TEORIA_RUNTIME_DATA_DATABASE_URL","TEORIA_OPA_CONTROL_PLANE_TOKEN"],
}
keys=required[sys.argv[1]] if sys.argv[1]!="all" else {key for group in required.values() for key in group}
missing=sorted(key for key in keys if not values.get(key) or "CHANGE_ME" in values[key])
if missing:sys.exit("Configure selected component Secret keys: "+", ".join(missing))
' "$component"
case "$component" in
  database|mlflow|platform|all)
    kubectl -n teoria get secret model-control -o json | python3 -c '
import base64,json,sys
values={k:base64.b64decode(v).decode() for k,v in json.load(sys.stdin)["data"].items()}
required={"database":["TEORIA_MLFLOW_DB_PASSWORD"],"mlflow":["MLFLOW_BACKEND_STORE_URI"],
"platform":["TEORIA_MODEL_ALLOWED_REGISTRIES","TEORIA_MODEL_STORAGE_ACCESS_KEY","TEORIA_MODEL_STORAGE_SECRET_KEY"]}
keys=required[sys.argv[1]] if sys.argv[1]!="all" else {key for group in required.values() for key in group}
missing=sorted(key for key in keys if not values.get(key) or "CHANGE_ME" in values[key])
if missing:sys.exit("Configure model-control keys: "+", ".join(missing))
' "$component"
    ;;
esac
goods_replicas=0
legal_replicas=0
if [[ "$component" == platform || "$component" == all || "$component" == mlflow ]]; then
  if ! kubectl -n teoria get configmap teoria-mlops-connections >/dev/null 2>&1; then
    kubectl -n teoria create configmap teoria-mlops-connections --from-env-file="$root/connections.env.example"
  fi
  connections=$(kubectl -n teoria get configmap teoria-mlops-connections -o json)
  activation=$(python3 -c '
import json,sys
values=json.load(sys.stdin).get("data",{})
keys=["TEORIA_MODEL_STORAGE_ENDPOINT"] if sys.argv[1]=="mlflow" else ["PREFECT_API_URL","MLFLOW_TRACKING_URI","TEORIA_MODEL_STORAGE_ENDPOINT","TEORIA_OPENMETADATA_BASE_URL","TEORIA_METADATA_SYNC_SCHEDULE_ENABLED","TEORIA_SPECIFICATION_PROCESSING_ENABLED","TEORIA_LEGAL_INFORMATION_ENABLED"]
missing=[key for key in keys if not values.get(key)]
if missing:sys.exit("Add explicit teoria-mlops-connections keys: "+", ".join(missing))
keys += [key for key in ("TEORIA_SPECIFICATION_UPLOAD_ENABLED",) if key in values]
if values.get("TEORIA_SPECIFICATION_UPLOAD_ENABLED")=="true" and values.get("TEORIA_SPECIFICATION_PROCESSING_ENABLED")!="true":sys.exit("Document uploads require specification processing")
for key in keys:
    if key.endswith("_ENABLED") and values[key] not in {"true","false"}:sys.exit(key+" must be true or false")
print(int(values.get("TEORIA_SPECIFICATION_PROCESSING_ENABLED")=="true"),int(values.get("TEORIA_LEGAL_INFORMATION_ENABLED")=="true"))
' "$component" <<< "$connections")
  read -r goods_replicas legal_replicas <<< "$activation"
fi
if [[ "$component" == platform || "$component" == all ]]; then
  kubectl -n teoria-models get secret model-images >/dev/null
  kubectl -n teoria-models get secret model-workload >/dev/null
  # Only enabled domain Jobs receive their own source credentials.
  kubectl -n teoria get secret teoria-secrets -o json | python3 -c '
import base64,json,sys
values=json.load(sys.stdin)["data"];keys=[]
if "1" in sys.argv[1:]:keys.append("TEORIA_PIPELINE_DATA_DATABASE_URL")
if sys.argv[2]=="1":keys.append("TEORIA_CONNECTOR_MOLEG_LAW_API_KEY")
if any(not values.get(k) or "CHANGE_ME" in base64.b64decode(values[k]).decode() for k in keys):
    sys.exit("Configure enabled domain source credentials")
' "$goods_replicas" "$legal_replicas"
fi
if [[ "$goods_replicas" == 1 ]]; then
  # Explicit feature credentials are checked before migrations or workload updates.
  kubectl -n teoria get secret specification-processing -o json | python3 -c '
import base64,json,sys
from urllib.parse import urlsplit
values={k:base64.b64decode(v).decode() for k,v in json.load(sys.stdin)["data"].items()}
keys=["TEORIA_SPECIFICATION_AUTHORING_API_URL","TEORIA_SPECIFICATION_AUTHORING_API_TOKEN","TEORIA_SPECIFICATION_ARTIFACT_ROOT","TEORIA_SPECIFICATION_S3_ENDPOINT","TEORIA_SPECIFICATION_S3_ACCESS_KEY","TEORIA_SPECIFICATION_S3_SECRET_KEY"]
if any(not values.get(k) or "CHANGE_ME" in values[k] for k in keys):sys.exit("Configure specification-processing Secret keys: "+", ".join(keys))
for key in (keys[0],keys[3]):
    value=urlsplit(values[key])
    if value.scheme not in {"http","https"} or not value.hostname or value.username or value.password or value.query or value.fragment:sys.exit("Invalid specification endpoint: "+key)
value=urlsplit(values[keys[2]])
if value.scheme!="s3" or not value.netloc or value.query or value.fragment:sys.exit("Specification artifacts require an S3 root")
'
  for secret in specification-codex authoring-codex; do
    kubectl -n teoria get secret "$secret" -o json | python3 -c '
import base64,json,sys
value=json.load(sys.stdin).get("data",{}).get("auth.json")
if not value or not isinstance(json.loads(base64.b64decode(value)),dict):sys.exit("Configure role-specific Codex auth.json Secret")
'
  done
fi
for selected in "${components[@]}"; do
  case "$selected" in
    database)
      render services/postgres | kubectl apply -f -
      for service in platform-postgres postgres; do kubectl -n teoria rollout status "statefulset/$service" --timeout=600s; done
      for job in $(component_jobs database); do run_job "$job"; done
      ;;
    storage)
      render services/minio | kubectl apply -f -
      kubectl -n teoria rollout status deployment/minio --timeout=600s
      run_job model-storage-init
      ;;
    workflow)
      render services/prefect | kubectl apply -f -
      kubectl -n teoria rollout status statefulset/prefect-redis --timeout=600s
      for service in prefect-server prefect-services; do kubectl -n teoria rollout status "deployment/$service" --timeout=600s; done
      ;;
    mlflow)
      render services/mlflow | kubectl apply -f -
      kubectl -n teoria rollout status deployment/mlflow --timeout=600s
      ;;
    openmetadata)
      render services/openmetadata/search.yaml | kubectl apply -f -
      kubectl -n teoria rollout status statefulset/openmetadata-search --timeout=600s
      run_job openmetadata-migrate
      render services/openmetadata | kubectl apply -f -
      kubectl -n teoria rollout status deployment/openmetadata-server --timeout=600s
      ;;
    platform)
      run_job app-postgres-migrate
      render teoria/runtime_storage.yaml | kubectl apply -f -
      run_job opa-bundle-build
      # Deployment verifies an already approved artifact; it never approves or publishes.
      run_job runtime-artifact-check
      kubectl create namespace teoria-pipelines --dry-run=client -o yaml | kubectl apply -f -
      render teoria/pipeline_execution | kubectl apply -f -
      kubectl kustomize "$root/base/teoria/model_execution" | kubectl apply -f -
      if [[ "$goods_replicas" == 1 || "$legal_replicas" == 1 ]]; then
        kubectl -n teoria get secret teoria-secrets -o json | python3 -c '
import json,sys
source=json.load(sys.stdin)["data"];items=[]
for enabled,name,keys in [(sys.argv[1],"teoria-pipeline-secrets",["TEORIA_PIPELINE_DATA_DATABASE_URL","PREFECT_API_AUTH_STRING"]),
(sys.argv[2],"teoria-legal-information-secrets",["TEORIA_PIPELINE_DATA_DATABASE_URL","PREFECT_API_AUTH_STRING","TEORIA_CONNECTOR_MOLEG_LAW_API_KEY"])]:
    if enabled=="1":items.append({"apiVersion":"v1","kind":"Secret","metadata":{"name":name,"namespace":"teoria-pipelines"},"type":"Opaque","data":{k:source[k] for k in keys}})
json.dump({"apiVersion":"v1","kind":"List","items":items},sys.stdout)
' "$goods_replicas" "$legal_replicas" | kubectl apply -f -
        kubectl -n teoria get secret teoria-registry -o json | python3 -c '
import json,sys
source=json.load(sys.stdin)
json.dump({"apiVersion":"v1","kind":"Secret","metadata":{"name":"teoria-registry","namespace":"teoria-pipelines"},"type":source["type"],"data":source["data"]},sys.stdout)
' | kubectl apply -f -
      fi
      if [[ "$goods_replicas" == 1 ]]; then
        kubectl -n teoria get secret specification-processing specification-codex -o json | python3 -c '
import json,sys
source=json.load(sys.stdin)["items"];items=[]
allowed={"TEORIA_SPECIFICATION_AUTHORING_API_URL","TEORIA_SPECIFICATION_AUTHORING_API_TOKEN","TEORIA_SPECIFICATION_ARTIFACT_ROOT","TEORIA_SPECIFICATION_S3_ENDPOINT","TEORIA_SPECIFICATION_S3_ACCESS_KEY","TEORIA_SPECIFICATION_S3_SECRET_KEY"}
for item in source:
    name=item["metadata"]["name"]
    keys=allowed if name=="specification-processing" else {"auth.json"}
    items.append({"apiVersion":"v1","kind":"Secret","metadata":{"name":name,"namespace":"teoria-pipelines"},"type":"Opaque","data":{k:v for k,v in item["data"].items() if k in keys}})
json.dump({"apiVersion":"v1","kind":"List","items":items},sys.stdout)
' | kubectl apply -f -
      fi
      pause_workers=true render teoria | kubectl apply -f -
      for service in admin-api admin-ui policy-control-plane opa runtime-api; do kubectl -n teoria rollout status "deployment/$service" --timeout=600s; done
      expected=$(python3 -c 'import json,sys; print(json.dumps({"metadata":True,"ontology":True,"mlops":True,"formatid":sys.argv[1]=="1","goods":sys.argv[1]=="1"}))' "$goods_replicas")
      kubectl -n teoria exec deployment/admin-api -- python -m teoria.entrypoints.deployment_check "$expected"
      if [[ "$goods_replicas" == 1 ]]; then
        kubectl -n teoria exec deployment/admin-api -- python -m teoria.domains.goods.data_processing.preflight
      fi
      for job in metadata-register model-register goods-register legal-register; do run_job "$job"; done
      for name in prefect-metadata-worker model-training-worker; do
        kubectl -n teoria scale "deployment/$name" --replicas=1
        kubectl -n teoria rollout status "deployment/$name" --timeout=600s
      done
      for entry in "prefect-worker:$goods_replicas" "prefect-law-worker:$legal_replicas"; do
        kubectl -n teoria scale "deployment/${entry%%:*}" --replicas="${entry##*:}"
        kubectl -n teoria rollout status "deployment/${entry%%:*}" --timeout=600s
      done
      ;;
  esac
done
printf 'Teoria component %s deployed; existing PVCs and data retained.\n' "$component"
