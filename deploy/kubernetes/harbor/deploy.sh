#!/usr/bin/env bash
# Install the independently managed Harbor release from a local, pinned chart.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
overlay=generic
chart=
values=
render=false
while (( $# )); do
  case "$1" in
    --overlay) overlay=${2:?overlay required}; shift 2 ;;
    --chart) chart=${2:?local chart archive required}; shift 2 ;;
    --values) values=${2:?private values file required}; shift 2 ;;
    --render) render=true; shift ;;
    *) echo "Unknown Harbor option: $1" >&2; exit 1 ;;
  esac
done
[[ "$overlay" == generic || "$overlay" == k3s || "$overlay" == k3d ]] || { echo 'Choose --overlay generic, k3s or k3d.' >&2; exit 1; }
[[ -f "$chart" && -f "$values" ]] || { echo 'Supply --chart with harbor-1.19.4.tgz and --values with a private configuration file.' >&2; exit 1; }
# Chart 1.19.4 / Harbor 2.15.4. No chart or image download is performed here.
expected=759872bbabaf05524268096b9d551a480d3f6814d13ed08723036e2673859182
actual=$(sha256sum "$chart")
[[ "${actual%% *}" == "$expected" ]] || { echo 'Harbor chart checksum mismatch.' >&2; exit 1; }
options=(-f "$root/values.yaml")
[[ "$overlay" == generic ]] || options+=(-f "$root/$overlay.yaml")
options+=(-f "$values")
if [[ "$render" == true ]]; then
  exec helm template harbor "$chart" --namespace harbor "${options[@]}"
fi
[[ "$(< "$values")" != *CHANGE_ME* ]] || { echo 'Replace CHANGE_ME in the private Harbor values file.' >&2; exit 1; }
kubectl -n harbor get secret harbor-tls harbor-secrets >/dev/null
# Leave failed resources/PVCs available for diagnosis. Never delete an installation.
exec helm upgrade --install harbor "$chart" --namespace harbor "${options[@]}" --wait --timeout 15m
