#!/usr/bin/env bash
# IP access is development-only. Preview needs only Python's standard library.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
for argument in "$@"; do
  case "$argument" in
    --apply|--verify|--recover|--restore-node)
      exec uv run --project "$root/backend" --locked --all-extras --group orchestration \
        python -m teoria.entrypoints.k3d_remote_access --root "$root" "$@"
      ;;
  esac
done
exec python3 "$root/backend/src/teoria/entrypoints/k3d_remote_access.py" --root "$root" "$@"
