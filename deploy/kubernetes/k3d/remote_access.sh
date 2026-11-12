#!/usr/bin/env bash
# IP access is a development-only profile. Production uses DNS and Ingress 443.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
exec uv run --project "$root/backend" --locked --all-extras --group orchestration \
  python -m teoria.entrypoints.k3d_remote_access --root "$root" \
  --platform-port "${TEORIA_K3D_PLATFORM_PORT:-18443}" \
  --harbor-port "${TEORIA_K3D_HARBOR_PORT:-18444}" "$@"
