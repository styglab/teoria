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
2. Set `TEORIA_METADATA_DB_PASSWORD` and
   `OPENMETADATA_INGESTION_BOT_TOKEN` outside the repository.
3. Run the one-shot PostgreSQL metadata workflow:

   ```bash
   docker compose --env-file deploy/compose/.env \
     -f deploy/compose/compose.yaml \
     --profile metadata --profile metadata-ingestion \
     run --rm openmetadata-ingestion-job
   ```

4. Verify the `ingestion` and `public_procurement` schemas in OpenMetadata.
5. Configure `TEORIA_OPENMETADATA_AUTH_TOKEN` with a read-only Teoria bot and
   set `TEORIA_OPENMETADATA_ENABLED=true` on `admin-api`.

The example enables metadata only. Profiler, sample data, usage, and query
lineage require a separate permission review and workflow. In particular,
`pg_stat_statements` is not required for schema metadata ingestion; its absence
only disables query/usage collection.

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
