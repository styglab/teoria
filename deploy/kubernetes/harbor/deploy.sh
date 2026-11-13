#!/usr/bin/env bash
# Install the independently managed Harbor release from a local, pinned chart.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
overlay=generic
chart=
values=
render=false
external_url=
environment=
while (( $# )); do
  case "$1" in
    --env) environment=${2:?dev or prod required}; shift 2 ;;
    --overlay) overlay=${2:?overlay required}; shift 2 ;;
    --chart) chart=${2:?local chart archive required}; shift 2 ;;
    --values) values=${2:?private values file required}; shift 2 ;;
    --render) render=true; shift ;;
    --external-url) external_url=${2:?external URL required}; shift 2 ;;
    *) echo "Unknown Harbor option: $1" >&2; exit 1 ;;
  esac
done
[[ "$overlay" == generic || "$overlay" == k3s || "$overlay" == k3d ]] || { echo 'Choose --overlay generic, k3s or k3d.' >&2; exit 1; }
chart_metadata=$(python3 - "$root/chart.json" <<'PYCHART'
import json,re,sys
value=json.load(open(sys.argv[1]))
if not all(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',value[key]) for key in ('version','app_version')) or not re.fullmatch('[a-f0-9]{64}',value['sha256']):
    sys.exit('Invalid Harbor chart metadata')
print(value['version'],value['app_version'],value['sha256'])
PYCHART
)
read -r chart_version app_version expected <<< "$chart_metadata"
if [[ -n "$environment" ]]; then
  [[ "$environment" == dev || "$environment" == prod ]] || { echo 'Choose --env dev or prod.' >&2; exit 1; }
  values=${values:-$root/../envs/$environment/harbor_values.yaml}
fi
if [[ -z "$chart" && "$overlay" == k3d ]]; then
  chart=$root/../k3d/.local/cache/charts/harbor-$chart_version.tgz
  [[ -f "$chart" ]] || chart=$root/../k3d/.local/harbor-$chart_version.tgz
fi
[[ -f "$chart" && -f "$values" ]] || { echo 'Supply the pinned local --chart and private --values file (or --env dev|prod).' >&2; exit 1; }
# Versions/checksum are owned by chart.json; no download is performed here.
actual=$(sha256sum "$chart")
[[ "${actual%% *}" == "$expected" ]] || { echo 'Harbor chart checksum mismatch.' >&2; exit 1; }
options=(-f "$root/values.yaml")
[[ "$overlay" == generic ]] || options+=(-f "$root/$overlay.yaml")
options+=(-f "$values")
if [[ "$render" != true && "${TEORIA_K3D_ACCESS_LOCK_HELD:-}" != 1 ]]; then
  exec 9>"${HOME}/.teoria-deploy.lock"
  flock -w 1200 9
fi
if [[ "$overlay" == k3d && -z "$external_url" ]]; then
  repository_root=$(cd -- "$root/../../.." && pwd)
  access_cli=$repository_root/backend/src/teoria/entrypoints/k3d_remote_access.py
  if [[ -f "$access_cli" ]]; then
    configured_registry=$(python3 "$access_cli" --root "$repository_root" --registry-host)
    [[ -z "$configured_registry" ]] || external_url=https://$configured_registry
  fi
fi
if [[ -n "$external_url" ]]; then
  python3 - "$external_url" <<'PYURL'
from urllib.parse import urlsplit
import sys
value=urlsplit(sys.argv[1])
try:
    valid=value.scheme=='https' and value.hostname and value.port!=0
except ValueError:
    valid=False
if not valid or value.username or value.password or value.path not in {'','/'} or value.query or value.fragment:
    sys.exit('Invalid Harbor public HTTPS origin')
PYURL
  options+=(--set-string "externalURL=$external_url")
fi
if [[ "$render" == true ]]; then
  exec helm template harbor "$chart" --namespace harbor "${options[@]}"
fi
[[ "$(< "$values")" != *CHANGE_ME* ]] || { echo 'Replace CHANGE_ME in the private Harbor values file.' >&2; exit 1; }
kubectl -n harbor get secret harbor-tls harbor-secrets >/dev/null
# Leave failed resources/PVCs available for diagnosis. Never delete an installation.
exec helm upgrade --install harbor "$chart" --namespace harbor "${options[@]}" --wait --timeout 15m
