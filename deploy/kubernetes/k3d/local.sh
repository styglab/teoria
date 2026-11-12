#!/usr/bin/env bash
# Local cluster lifecycle; application deployment stays in ../deploy.sh.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
action=${1:-help}
shift || true
if [[ "$action" == --help || "$action" == -h ]]; then action=help; fi
export TEORIA_K3D_DATA_DIR=${TEORIA_K3D_DATA_DIR:-$HOME/.local/share/teoria/k3d}
export KUBECONFIG=${TEORIA_K3D_KUBECONFIG:-$root/deploy/kubernetes/k3d/.local/kubeconfig}
export TEORIA_K3D_HTTP_PORT=${TEORIA_K3D_HTTP_PORT:-8080}
export TEORIA_K3D_HTTPS_PORT=${TEORIA_K3D_HTTPS_PORT:-8443}
local_dir=$root/deploy/kubernetes/k3d/.local
revision=${TEORIA_K3D_REVISION:-}
if [[ -z "$revision" && ( "$action" == build || "$action" == deploy || "$action" == render ) ]]; then
  revision=$(git -C "$root" rev-parse HEAD)
fi
image_prefix=harbor.teoria.localhost/teoria
registry_options=()
if [[ -f "$local_dir/remote_access/config.json" ]]; then
  registry_host=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["harbor_url"].removeprefix("https://"))' "$local_dir/remote_access/config.json")
  image_prefix=$registry_host/teoria
  registry_options=(--model-registry-host "$registry_host" --model-registry-url "https://$registry_host")
fi
check_context() {
  [[ $(kubectl config current-context) == k3d-teoria ]] || {
    echo 'Expected the dedicated k3d-teoria context; run local.sh up first.' >&2; exit 1;
  }
}
case "$action" in
  up)
    command -v k3d >/dev/null
    command -v openssl >/dev/null
    docker info >/dev/null
    [[ "$TEORIA_K3D_DATA_DIR" == /* && "$TEORIA_K3D_DATA_DIR" != *:* ]] || {
      echo 'TEORIA_K3D_DATA_DIR must be an absolute Docker-host path without colons.' >&2; exit 1;
    }
    umask 077
    mkdir -p "$local_dir" "$(dirname -- "$KUBECONFIG")"
    # Bind paths belong to the Docker host, which can differ from a devcontainer.
    if ! k3d cluster list -o json | python3 -c 'import json,sys; sys.exit(not any(c["name"]=="teoria" for c in json.load(sys.stdin)))'; then
      k3d cluster create --config "$root/deploy/kubernetes/k3d/cluster.yaml"
    else
      if ! docker inspect k3d-teoria-serverlb --format '{{json .HostConfig.PortBindings}}' | python3 -c 'import json,sys; sys.exit(not any(p.get("HostPort")=="443" for p in (json.load(sys.stdin).get("443/tcp") or [])))'; then
        echo 'Existing cluster predates Harbor. Follow docs/deployment/image_registry.md migration before recreating it; no data was deleted.' >&2
        exit 1
      fi
      k3d cluster start teoria
    fi
    k3d kubeconfig get teoria > "$KUBECONFIG"
    # A devcontainer may reach the node by Docker DNS instead of host loopback.
    if [[ -n "${TEORIA_K3D_API_SERVER:-}" ]]; then
      kubectl config set-cluster k3d-teoria --server="$TEORIA_K3D_API_SERVER" >/dev/null
    fi
    check_context
    kubectl wait --for=condition=Ready nodes --all --timeout=180s
    kubectl -n kube-system wait --for=create deployment/coredns \
      deployment/local-path-provisioner deployment/traefik --timeout=180s
    for component in local-path-provisioner traefik; do
      kubectl -n kube-system rollout status "deployment/$component" --timeout=180s
    done
    kubectl apply -f "$root/deploy/kubernetes/overlays/k3s/traefik_config.yaml"
    kubectl apply -f "$root/deploy/kubernetes/k3d/storage.yaml"
    kubectl apply -f "$root/deploy/kubernetes/k3d/dns.yaml"
    kubectl -n kube-system rollout restart deployment/coredns
    kubectl -n kube-system rollout status deployment/coredns --timeout=120s
    kubectl create namespace teoria --dry-run=client -o yaml | kubectl apply -f -
    if [[ ! -f "$local_dir/tls.crt" || ! -f "$local_dir/tls.key" ]]; then
      openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
        -keyout "$local_dir/tls.key" -out "$local_dir/tls.crt" \
        -subj /CN=teoria.localhost \
        -addext 'subjectAltName=DNS:teoria.localhost' 2>/dev/null
    fi
    kubectl -n teoria create secret tls teoria-tls \
      --cert="$local_dir/tls.crt" --key="$local_dir/tls.key" \
      --dry-run=client -o yaml | kubectl apply -f -
    # Harbor is installed separately after the cluster is ready. Its public name
    # must work for host Docker, node containerd and Pods (including token URLs).
    if [[ ! -f "$local_dir/harbor.crt" || ! -f "$local_dir/harbor.key" ]]; then
      openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
        -keyout "$local_dir/harbor.key" -out "$local_dir/harbor.crt" \
        -subj /CN=harbor.teoria.localhost \
        -addext 'subjectAltName=DNS:harbor.teoria.localhost' 2>/dev/null
    fi
    kubectl create namespace harbor --dry-run=client -o yaml | kubectl apply -f -
    kubectl -n harbor create secret tls harbor-tls \
      --cert="$local_dir/harbor.crt" --key="$local_dir/harbor.key" \
      --dry-run=client -o yaml | kubectl apply -f -
    docker cp "$local_dir/harbor.crt" k3d-teoria-server-0:/etc/rancher/k3s/harbor_ca.crt
    loadbalancer_ip=$(docker inspect --format '{{(index .NetworkSettings.Networks "k3d-teoria").IPAddress}}' k3d-teoria-serverlb)
    docker exec k3d-teoria-server-0 cat /etc/hosts > "$local_dir/node_hosts"
    python3 - "$local_dir/node_hosts" "$loadbalancer_ip" <<'PYHOSTS'
import ipaddress, pathlib, sys
path = pathlib.Path(sys.argv[1])
address = str(ipaddress.ip_address(sys.argv[2]))
lines = [line for line in path.read_text().splitlines() if 'harbor.teoria.localhost' not in line.split('#')[0].split()]
path.write_text('\n'.join(lines) + '\n' + address + ' harbor.teoria.localhost\n')
PYHOSTS
    docker exec -i k3d-teoria-server-0 sh -c 'cat > /etc/hosts' < "$local_dir/node_hosts"
    if [[ -f "$local_dir/remote_access/config.json" ]]; then
      bash "$root/deploy/kubernetes/k3d/remote_access.sh" --restore-node
      if [[ $(docker inspect --format '{{index .Config.Labels "io.teoria.role"}}' teoria-k3d-remote-access 2>/dev/null) == k3d-remote-access ]]; then
        docker start teoria-k3d-remote-access >/dev/null
      fi
    fi
    printf 'Cluster ready. Kubeconfig: %s\nLocal TLS certificate: %s\n' "$KUBECONFIG" "$local_dir/tls.crt"
    ;;
  build)
    export DOCKER_BUILDKIT=1
    docker buildx version >/dev/null 2>&1 || { echo 'Image builds require the Docker Buildx plugin; prebuilt images can be pushed separately.' >&2; exit 1; }
    docker info >/dev/null
    [[ "$revision" =~ ^[a-f0-9]{40}$ ]] || { echo 'Use a full commit SHA for TEORIA_K3D_REVISION.' >&2; exit 1; }
    (( $# == 0 )) || { echo 'Build uses the complete Teoria image set; no feature selection is supported.' >&2; exit 1; }
    image_specs=(
      'runtime backend/Dockerfile runtime'
      'authoring backend/Dockerfile authoring'
      'admin-ui frontend/Dockerfile standalone'
      'pipelines backend/Dockerfile kubernetes-worker'
      'specification-job backend/Dockerfile worker'
      'legal-job backend/Dockerfile law-worker'
      'metadata-worker backend/Dockerfile metadata-worker'
      'opa deploy/image_builds/opa/Dockerfile runtime'
      'opa-builder deploy/image_builds/opa/Dockerfile bundle_builder'
      'ingestion deploy/image_builds/openmetadata/Dockerfile -'
      'mlflow backend/Dockerfile mlflow'
      'model-dispatcher backend/Dockerfile model-dispatcher'
    )
    for spec in "${image_specs[@]}"; do
      read -r name dockerfile target <<< "$spec"
      image=$image_prefix/$name:$revision
      options=()
      [[ "$target" == - ]] || options+=(--target "$target")
      docker build -f "$root/$dockerfile" "${options[@]}" -t "$image" "$root"
      docker push "$image"
    done
    ;;
  deploy|render)
    if [[ "$action" == render ]]; then set -- --render "$@"; fi
    render_only=false
    for option in "$@"; do
      [[ "$option" != --render ]] || render_only=true
    done
    if [[ "$render_only" != true ]]; then check_context; fi
    exec bash "$root/deploy/kubernetes/deploy.sh" "$image_prefix" "$revision" teoria.localhost --overlay k3d "${registry_options[@]}" "$@"
    ;;
  status)
    check_context
    kubectl -n teoria get deployments,statefulsets,pvc,ingress
    for namespace in harbor teoria-models; do
      if [[ -n $(kubectl get namespace "$namespace" --ignore-not-found -o name) ]]; then
        kubectl -n "$namespace" get deployments,statefulsets,jobs
      fi
    done
    if [[ -f "$local_dir/access.json" ]]; then
      python3 - "$local_dir/access.json" <<'PYACCESS'
import json,sys
value=json.load(open(sys.argv[1]))
for key in ('platform_url','harbor_url'):
    if value.get(key):print(key+': '+value[key])
PYACCESS
    fi
    ;;
  stop)
    if [[ $(docker inspect --format '{{index .Config.Labels "io.teoria.role"}}' teoria-k3d-remote-access 2>/dev/null) == k3d-remote-access ]]; then
      docker stop teoria-k3d-remote-access >/dev/null
    fi
    k3d cluster stop teoria
    ;;
  *)
    cat <<'HELP'
Usage: bash deploy/kubernetes/k3d/local.sh ACTION [options]

  up                              Start the cluster and local DNS/TLS/storage
  build           Build and push development images (optional)
  render          Review platform YAML without deploying
  deploy          Update Teoria only
  deploy --component all
                                  First installation of managed MLOps services
  status                          Show workloads and saved public URLs
  stop                            Stop the cluster; keep its data

Components: platform (default), database, storage, workflow, mlflow, openmetadata, all.
Metadata, Ontology and MLOps run together. Domain activation uses the operational ConfigMap.
Harbor and remote IP access are separate setup steps; see deploy/README.md.
HELP
    [[ "$action" == help ]] || exit 1
    ;;
esac
