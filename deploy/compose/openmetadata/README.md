# OpenMetadata development integration

OpenMetadata is an optional Metadata Foundation in the main Compose deployment.
Its database and search index are not Teoria application or data stores.

```bash
docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml \
  --profile metadata up -d
```

The default `metadata` profile runs only the catalog control plane:

- OpenMetadata Server
- the `openmetadata_db` database in the shared platform PostgreSQL instance
- Elasticsearch
- the one-shot schema migration

It does not run Airflow. Teoria Prefect owns ingestion schedules and retries,
while each OpenMetadata workflow runs in an isolated, ephemeral ingestion
container.

After the server is healthy:

1. Keep the default ingestion bot JWT outside the repository (or create a
   dedicated least-privilege bot for Teoria).
2. Build the thin ingestion image and set `TEORIA_METADATA_DB_PASSWORD` and
   `OPENMETADATA_INGESTION_BOT_TOKEN` outside the repository.
3. Run the one-shot PostgreSQL metadata workflow:

   ```bash
   docker compose --env-file deploy/compose/.env \
     -f deploy/compose/compose.yaml \
     --profile metadata --profile metadata-ingestion \
     run --rm openmetadata-ingestion-job
   ```

4. Verify the `public_procurement` schema in OpenMetadata.
5. Configure `TEORIA_OPENMETADATA_AUTH_TOKEN` with a read-only Teoria bot and
   set `TEORIA_OPENMETADATA_ENABLED=true` on `admin-api`.

To validate the Prefect-owned path, start the dedicated worker and trigger its
metadata-profile deployment:

```bash
docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml \
  --profile metadata --profile metadata-orchestration \
  up -d --build prefect-metadata-worker

docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml \
  --profile metadata --profile metadata-orchestration \
  exec prefect-metadata-worker \
  prefect deployment run \
  'OpenMetadata PostgreSQL 메타데이터 동기화/openmetadata-postgres-metadata-sync' \
  --watch
```

The worker uses the host Docker socket and is intentionally isolated from the
normal data-ingestion worker. Do not use this pattern in k3s; use a dedicated
Kubernetes work pool and ephemeral namespaced Job there. The worker also
requires an exact image allowlist match, so deployment parameters cannot be
used to launch an arbitrary image through the socket.

The example enables metadata only. Profiler, sample data, usage, and query
lineage require a separate permission review and workflow. In particular,
`pg_stat_statements` is not required for schema metadata ingestion; its absence
only disables query/usage collection.

The default catalog intentionally excludes the DataOps-only `ingestion` schema.
That schema contains raw provider payloads, checkpoints, retry queues, and run
audit state rather than business data assets. The OpenMetadata reader therefore
has access only to `public_procurement`. If operational metadata discovery is
needed later, expose `ingestion` through a separate opt-in database service and
Domain with a dedicated reader instead of mixing it into the business catalog.

The Compose deployment runs OpenMetadata schema migrations before the server.
Prefect owns metadata-ingestion scheduling, retry, timeout, and ordering. The
OpenMetadata ingestion image owns connector execution and writes results to the
OpenMetadata REST API. Do not install `openmetadata-ingestion` into the normal
Teoria Prefect worker image.

In Docker Compose development, the command above is the supported one-shot
boundary. A dedicated Docker work pool may invoke the same container, but it
must be isolated from the normal process worker because Docker socket access is
host-privileged. In k3s, use a Prefect Kubernetes work pool to create an
ephemeral Job with the same pinned ingestion image and configuration.

OpenMetadata UI metadata exploration remains available. Creating, scheduling,
or retrying ingestion pipelines from the OpenMetadata UI is intentionally not
available in this external-orchestration mode; use Prefect for those operations.
