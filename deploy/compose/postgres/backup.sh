#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
compose_file="$repo_root/deploy/compose/compose.yaml"
env_file=${TEORIA_ENV_FILE:-"$repo_root/deploy/compose/.env"}
compose=(docker compose --env-file "$env_file" -f "$compose_file")

# Resolve the same project and Data DB URL as deployment, including shell overrides.
# Keep the resolved configuration and credentials in memory, never in backup metadata.
config_json=$("${compose[@]}" config --format json)
config_value() {
  printf '%s' "$config_json" | python3 -c \
    'import json,sys; value=json.load(sys.stdin)
for key in sys.argv[1:]: value=value[key]
print(value)' "$@"
}
project=$(config_value name)
data_url=$(config_value services postgres-migrate environment TEORIA_PIPELINE_DATA_DATABASE_URL)
backup_root=${TEORIA_BACKUP_ROOT:-"$repo_root/backups"}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="$backup_root/$project/$timestamp"
staging_dir="$backup_dir.incomplete"

mkdir -p "$backup_root/$project"
mkdir "$staging_dir"
trap 'printf "Backup incomplete: %s\n" "$staging_dir" >&2' ERR

# Use the full URI, including TLS options. Send it to the container over stdin
# so it is absent from host command arguments and persistent container settings.
data_database() {
  printf '%s\n' "$data_url" | "${compose[@]}" exec -T postgres sh -ec \
    'IFS= read -r connection; exec "$@" --dbname "$connection"' sh "$@"
}

data_database pg_dump -Fc > "$staging_dir/teoria_data.dump" \
  2> "$staging_dir/teoria_data.stderr.log"
data_database psql -Atc 'show server_version' \
  > "$staging_dir/teoria_data_postgresql_version.txt" \
  2>> "$staging_dir/teoria_data.stderr.log"

platform_databases=(teoria_app prefect openmetadata_db)
if [ "$("${compose[@]}" exec -T platform-postgres psql -U platform_admin -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = 'mlflow'")" = "1" ]; then
  platform_databases+=(mlflow)
fi
for database in "${platform_databases[@]}"; do
  "${compose[@]}" exec -T platform-postgres \
    pg_dump -U platform_admin -d "$database" -Fc > "$staging_dir/$database.dump" \
    2> "$staging_dir/$database.stderr.log"
done
"${compose[@]}" exec -T platform-postgres \
  psql -U platform_admin -d postgres -Atc 'show server_version' \
  > "$staging_dir/platform_postgresql_version.txt"

# Check that every archive can be read before marking the whole backup complete.
for database in teoria_data "${platform_databases[@]}"; do
  "${compose[@]}" exec -T postgres pg_restore --list \
    < "$staging_dir/$database.dump" > /dev/null \
    2>> "$staging_dir/$database.stderr.log"
done
(
  cd "$staging_dir"
  sha256sum -- *.dump > SHA256SUMS
  sha256sum --check --status SHA256SUMS
)
printf 'project=%s\ncreated_at=%s\ndata_database_source=resolved_pipeline_database_url\n' \
  "$project" "$timestamp" > "$staging_dir/backup_info.txt"
mv -- "$staging_dir" "$backup_dir"
trap - ERR

printf 'Backup completed: %s\n' "$backup_dir"
printf 'Verify with: (cd %q && sha256sum -c SHA256SUMS)\n' "$backup_dir"
