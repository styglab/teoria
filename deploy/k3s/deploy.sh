#!/usr/bin/env bash
# Called by GitHub Actions on the EC2 host; no cluster credentials leave EC2.
set -Eeuo pipefail
image_prefix=${1:?image registry prefix required}
revision=${2:?commit SHA required}
public_host=${3:?public DNS name required}
[[ "$revision" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid commit SHA' >&2; exit 1; }
[[ "$image_prefix" =~ ^ghcr\.io/[a-z0-9_./-]+$ ]] || { echo 'Invalid GHCR image prefix' >&2; exit 1; }
[[ "$public_host" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || { echo 'Invalid public hostname' >&2; exit 1; }
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
command -v kubectl >/dev/null
command -v python3 >/dev/null
# Also serialize manual deploys and preserve a failed release for diagnosis.
exec 9>"${HOME}/.teoria-deploy.lock"
flock -w 1200 9
kubectl get nodes >/dev/null
kubectl create namespace teoria --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace teoria-pipelines --dry-run=client -o yaml | kubectl apply -f -
for secret in teoria-secrets teoria-registry teoria-tls; do
  kubectl -n teoria get secret "$secret" >/dev/null || {
    echo "Create Kubernetes Secret $secret according to docs/deployment/k3s.md" >&2; exit 1;
  }
done
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
scratch=$(mktemp -d "$root/.release_XXXXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
trap 'echo "Deployment failed; existing PVCs and release files are retained. Check Kubernetes Job/Pod status." >&2' ERR
render() {
  python3 - "$root" "$scratch" "$1" "$image_prefix" "$revision" "$public_host" <<'PY'
import json,os,sys
root,out,resource,prefix,revision,host=sys.argv[1:]
images=['runtime','authoring','admin-ui','nginx','pipelines','metadata-worker','opa','opa-builder','ingestion']
config={'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization',
        'namespace':'teoria-pipelines' if resource=='execution' else 'teoria',
        'resources':[os.path.relpath(root+'/'+resource,out)],
        'images':[{'name':'teoria/'+name,'newName':prefix+'/'+name,'newTag':revision} for name in images]}
def patch(kind,name,body):
    config.setdefault('patches',[]).append({'target':{'kind':kind,'name':name},'patch':json.dumps(body)})
if resource=='application':
    patch('Ingress','teoria',[
        {'op':'replace','path':'/spec/rules/0/host','value':host},
        {'op':'replace','path':'/spec/tls/0/hosts/0','value':host}])
    # Kubernetes image transforms do not touch environment variables.
    patch('Deployment','prefect-metadata-worker',{
        'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'prefect-metadata-worker'},
        'spec':{'template':{'spec':{'containers':[{'name':'prefect-metadata-worker','env':[
            {'name':'TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE','value':prefix+'/ingestion:'+revision}]}]}}}})
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
    if [[ "$state" == failed ]]; then echo "Job $name failed; inspect its Pod logs on EC2." >&2; return 1; fi
    sleep 3
  done
  echo "Timed out waiting for Job $name" >&2
  return 1
}
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
for service in policy-control-plane opa runtime-api admin-api admin-ui nginx prefect-server prefect-services; do
  kubectl -n teoria rollout status "deployment/$service" --timeout=600s
done
run_job prefect-register
for service in prefect-worker prefect-metadata-worker; do
  kubectl -n teoria rollout status "deployment/$service" --timeout=600s
done
# Verify public routing on EC2 itself; this also exercises nginx's upstream DNS.
kubectl -n teoria exec deployment/admin-api -- python -c \
  'import os,json,urllib.request; r=urllib.request.Request("http://nginx/admin-api/v1/admin/auth/session",headers={"Authorization":"Bearer "+os.environ["TEORIA_ADMIN_API_TOKEN"]}); assert urllib.request.urlopen(r,timeout=20).status==200; print("Admin proxy authentication verified")'
kubectl -n teoria exec deployment/admin-api -- python -c \
  'import os,json,urllib.request; r=urllib.request.Request("http://runtime-api:8000/v1/version",headers={"Authorization":"Bearer "+os.environ["TEORIA_CONTEXT_RUNTIME_API_TOKEN"]}); d=json.load(urllib.request.urlopen(r,timeout=20)); assert d["runtime_artifact"]["bundle_checksum"]; print("Published Runtime artifact verified:", d["runtime_artifact"]["version"])'
kubectl -n teoria exec deployment/admin-api -- python -c \
  'import os,json,urllib.request; r=urllib.request.Request("http://nginx/admin-api/v1/admin/metadata/status",headers={"Authorization":"Bearer "+os.environ["TEORIA_ADMIN_API_TOKEN"]}); assert json.load(urllib.request.urlopen(r,timeout=20))["available"]; print("OpenMetadata connection verified")'
kubectl -n teoria exec deployment/admin-api -- python -c \
  'import sys,urllib.request; assert urllib.request.urlopen("https://"+sys.argv[1]+"/health",timeout=20).status==200; print("Public HTTPS ingress verified")' "$public_host"
printf 'Deployed commit %s to https://%s\n' "$revision" "$public_host"
