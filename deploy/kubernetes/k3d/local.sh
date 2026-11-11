#!/usr/bin/env bash
# Local cluster lifecycle; application deployment stays in ../deploy.sh.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
action=${1:-help}
shift || true
export TEORIA_K3D_DATA_DIR=${TEORIA_K3D_DATA_DIR:-$HOME/.local/share/teoria/k3d}
export KUBECONFIG=${TEORIA_K3D_KUBECONFIG:-$root/deploy/kubernetes/k3d/.local/kubeconfig}
local_dir=$root/deploy/kubernetes/k3d/.local
revision=${TEORIA_K3D_REVISION:-$(git -C "$root" rev-parse HEAD)}
image_prefix=localhost:5111/teoria
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
      k3d cluster start teoria
    fi
    k3d kubeconfig get teoria > "$KUBECONFIG"
    check_context
    kubectl wait --for=condition=Ready nodes --all --timeout=180s
    kubectl -n kube-system wait --for=create deployment/coredns \
      deployment/local-path-provisioner deployment/traefik --timeout=180s
    for component in local-path-provisioner traefik; do
      kubectl -n kube-system rollout status "deployment/$component" --timeout=180s
    done
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
    # The loopback-only development registry requires no credentials.
    printf '{"auths":{}}\n' > "$local_dir/docker_config.json"
    kubectl -n teoria create secret generic teoria-registry \
      --type=kubernetes.io/dockerconfigjson --from-file=".dockerconfigjson=$local_dir/docker_config.json" \
      --dry-run=client -o yaml | kubectl apply -f -
    printf 'Cluster ready. Kubeconfig: %s\nLocal TLS certificate: %s\n' "$KUBECONFIG" "$local_dir/tls.crt"
    ;;
  build)
    export DOCKER_BUILDKIT=1
    [[ $(docker inspect --format '{{.State.Running}}' k3d-teoria-images 2>/dev/null) == true ]] || {
      echo 'The local image registry is not running; run local.sh up first.' >&2; exit 1;
    }
    [[ "$revision" =~ ^[a-f0-9]{40}$ ]] || { echo 'Use a full commit SHA for TEORIA_K3D_REVISION.' >&2; exit 1; }
    modules=semantic
    while (( $# )); do
      case "$1" in
        --modules) modules=${2:?modules required}; shift 2 ;;
        *) echo "Unknown build option: $1" >&2; exit 1 ;;
      esac
    done
    case "$modules" in
      semantic)
        image_specs=(
          'runtime backend/Dockerfile runtime'
          'authoring backend/Dockerfile authoring'
          'admin-ui frontend/Dockerfile standalone'
          'pipelines backend/Dockerfile kubernetes-worker'
          'metadata-worker backend/Dockerfile metadata-worker'
          'opa deploy/compose/opa/Dockerfile runtime'
          'opa-builder deploy/compose/opa/Dockerfile bundle_builder'
          'ingestion deploy/compose/openmetadata/Dockerfile -'
        ) ;;
      mlops)
        image_specs=(
          'admin backend/Dockerfile admin'
          'authoring backend/Dockerfile authoring'
          'admin-ui frontend/Dockerfile standalone'
          'mlflow backend/Dockerfile mlflow'
          'model-dispatcher backend/Dockerfile model-dispatcher'
        ) ;;
      *) echo 'Choose --modules semantic or mlops' >&2; exit 1 ;;
    esac
    for spec in "${image_specs[@]}"; do
      read -r name dockerfile target <<< "$spec"
      image=$image_prefix/$name:$revision
      options=()
      [[ "$target" == - ]] || options+=(--target "$target")
      docker build -f "$root/$dockerfile" "${options[@]}" -t "$image" "$root"
      docker push "$image"
    done
    ;;
  deploy)
    render_only=false
    for option in "$@"; do
      [[ "$option" != --render ]] || render_only=true
    done
    if [[ "$render_only" != true ]]; then check_context; fi
    exec bash "$root/deploy/kubernetes/deploy.sh" "$image_prefix" "$revision" teoria.localhost --overlay k3d "$@"
    ;;
  stop)
    k3d cluster stop teoria
    ;;
  *)
    echo 'Usage: bash deploy/kubernetes/k3d/local.sh {up|build [--modules semantic|mlops]|deploy [--modules semantic|mlops] [--render]|stop}'
    [[ "$action" == help ]] || exit 1
    ;;
esac
