#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
compose_file="$repo_root/deploy/compose/compose.yaml"
backup_root=${TEORIA_BACKUP_ROOT:-"$repo_root/backups"}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="$backup_root/$timestamp"

mkdir -p "$backup_dir"

docker compose -f "$compose_file" exec -T postgres \
  pg_dump -U teoria_pipeline -d teoria_data -Fc > "$backup_dir/teoria_data.dump"

for database in teoria_app prefect openmetadata_db; do
  docker compose -f "$compose_file" exec -T platform-postgres \
    pg_dump -U platform_admin -d "$database" -Fc > "$backup_dir/$database.dump"
done

docker compose -f "$compose_file" exec -T postgres \
  psql -U teoria_pipeline -d teoria_data -Atc 'show server_version' \
  > "$backup_dir/teoria_data-postgresql-version.txt"
docker compose -f "$compose_file" exec -T platform-postgres \
  psql -U platform_admin -d postgres -Atc 'show server_version' \
  > "$backup_dir/platform-postgresql-version.txt"

(
  cd "$backup_dir"
  sha256sum -- *.dump > SHA256SUMS
)

printf 'Backup completed: %s\n' "$backup_dir"
printf 'Verify with: (cd %q && sha256sum -c SHA256SUMS)\n' "$backup_dir"
