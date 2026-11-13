#!/usr/bin/env bash
# Prepare environment inputs or register one ConfigMap/Secret in an explicit cluster.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
action=${1:-help}
shift || true
environment=
context=
role=
directory=
while (( $# )); do
  case "$1" in
    --env) environment=${2:?dev or prod required}; shift 2 ;;
    --context) context=${2:?kubectl context required}; shift 2 ;;
    --role) role=${2:?Secret role required}; shift 2 ;;
    --dir) directory=${2:?private directory required}; shift 2 ;;
    *) echo "Unknown settings option: $1" >&2; exit 1 ;;
  esac
done
if [[ "$action" == help || "$action" == --help || "$action" == -h ]]; then
  cat <<'HELP'
Usage:
  settings.sh init  --env dev|prod [--dir PRIVATE_DIRECTORY]
  settings.sh apply --env dev|prod --context CONTEXT --role connections|platform|control|workload|specification|harbor [--dir PRIVATE_DIRECTORY]

init copies examples without replacing existing values; it never contacts Kubernetes.
apply updates only the selected ConfigMap or Secret and never switches your current context.
Certificates, Registry pull authentication and Codex auth remain separate inputs.
HELP
  exit 0
fi
[[ "$environment" == dev || "$environment" == prod ]] || { echo 'Specify --env dev or --env prod.' >&2; exit 1; }
directory=${directory:-$root/$environment}
case "$action" in
  init)
    [[ -z "$context" && -z "$role" ]] || { echo 'init does not use --context or --role.' >&2; exit 1; }
    umask 077
    mkdir -p -- "$directory"
    chmod 700 -- "$directory"
    for name in connections secrets control workload specification harbor_secrets; do
      target=$directory/$name.env
      [[ ! -L "$target" ]] || { echo 'Use --dir for an external private directory instead of symlinked input files.' >&2; exit 1; }
      if [[ ! -e "$target" ]]; then
        # noclobber protects credentials if another initialization races this one.
        (set -o noclobber; cat "$root/$environment/$name.env.example" > "$target")
      fi
      chmod 600 -- "$target"
    done
    printf 'Private %s inputs prepared in %s; fill values before registration.\n' "$environment" "$directory"
    ;;
  apply)
    [[ -n "$context" ]] || { echo 'Specify the destination with --context.' >&2; exit 1; }
    case "$role" in
      harbor) file=harbor_secrets.env; namespace=harbor; resource=harbor-secrets; kind=secret ;;
      connections) file=connections.env; namespace=teoria; resource=teoria-mlops-connections; kind=configmap ;;
      platform) file=secrets.env; namespace=teoria; resource=teoria-secrets; kind=secret ;;
      control) file=control.env; namespace=teoria; resource=model-control; kind=secret ;;
      workload) file=workload.env; namespace=teoria-models; resource=model-workload; kind=secret ;;
      specification) file=specification.env; namespace=teoria; resource=specification-processing; kind=secret ;;
      *) echo 'Choose --role connections, platform, control, workload, specification or harbor.' >&2; exit 1 ;;
    esac
    [[ -f "$directory/$file" && ! -L "$directory/$file" ]] || { echo "Prepare $file with init first." >&2; exit 1; }
    [[ $(stat -c '%a' -- "$directory") == 700 && $(stat -c '%a' -- "$directory/$file") == 600 ]] || { echo 'Set the private directory to 700 and env file to 600 before registration.' >&2; exit 1; }
    if grep -qE '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=.*CHANGE_ME' "$directory/$file"; then
      echo "Replace CHANGE_ME in $file before registration." >&2; exit 1
    fi
    if [[ "$role" == connections ]]; then
      # ConfigMap inputs are an explicit public contract, not a place for credential keys.
      while IFS='=' read -r key value || [[ -n "$key" ]]; do
        [[ -n "$key" && ! "$key" =~ ^[[:space:]]*# && ! "$key" =~ ^[[:space:]]*$ ]] || continue
        if [[ ! "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || ! grep -q "^${key}=" "$root/$environment/connections.env.example"; then
          echo 'Unknown connections key; use the environment example and keep credentials in Secret role files.' >&2
          exit 1
        fi
      done < "$directory/$file"
    fi
    [[ $(kubectl config get-contexts "$context" -o name) == "$context" ]] || { echo 'Destination context was not found.' >&2; exit 1; }
    kubectl --context "$context" get namespace "$namespace" >/dev/null
    creation=(kubectl --context "$context" -n "$namespace" create "$kind")
    manager=teoria-env-connections
    if [[ "$kind" == secret ]]; then
      creation+=(generic)
      manager=teoria-env-secrets
    fi
    "${creation[@]}" "$resource" --from-env-file="$directory/$file" --dry-run=client -o yaml |
      kubectl --context "$context" -n "$namespace" apply --server-side --field-manager="$manager" -f -
    printf 'Registered %s: context=%s namespace=%s %s=%s.\n' "$environment" "$context" "$namespace" "$kind" "$resource"
    case "$role" in
      harbor)
        echo 'Next: update the Harbor Helm release; coordinate existing password/key rotation separately.' ;;
      connections)
        echo 'Next: deploy --component platform; also deploy --component mlflow if the object-store endpoint changed.' ;;
      platform)
        echo 'Next: deploy the affected platform/service component; coordinate real database/password rotation separately.' ;;
      control)
        echo 'Next: deploy --component platform; also deploy --component mlflow if its database credentials changed.' ;;
      workload)
        echo 'Next: new model Jobs read this Secret; explicitly redeploy existing model serving workloads that need the new values.' ;;
      specification)
        echo 'Next: deploy --component platform; running specification Jobs retain their environment until explicitly rerun.' ;;
    esac
    ;;
  *) echo 'Choose init or apply.' >&2; exit 1 ;;
esac
