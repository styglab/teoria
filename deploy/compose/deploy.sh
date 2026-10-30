#!/usr/bin/env bash
set -euo pipefail
compose_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$compose_root/../../backend/src/teoria/entrypoints/compose_deployment.py" "$@"
