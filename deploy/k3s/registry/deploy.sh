#!/usr/bin/env bash
# Independent registry bootstrap; no platform images or application secrets are needed.
set -euo pipefail
registry_host=${1:?registry hostname required}
[[ "$registry_host" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || { echo 'Invalid registry hostname' >&2; exit 1; }
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
kubectl get namespace teoria-registry >/dev/null
for secret in registry-auth registry-tls; do
  kubectl -n teoria-registry get secret "$secret" >/dev/null
done
kubectl kustomize "$root" | python3 -c '
import sys
host=sys.argv[1]
sys.stdout.write(sys.stdin.read().replace("registry.teoria.invalid",host))
' "$registry_host" | kubectl apply -f -
kubectl -n teoria-registry rollout status deployment/image-registry --timeout=300s
