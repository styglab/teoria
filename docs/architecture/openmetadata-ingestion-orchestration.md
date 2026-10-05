# OpenMetadata ingestion orchestration

## Decision

Teoria uses Prefect as the single workflow orchestrator. OpenMetadata is the
metadata catalog and authoritative metadata service; it does not run an
always-on Airflow stack in Teoria deployments.

```text
Prefect schedule / retry / timeout
              |
              v
ephemeral OpenMetadata ingestion Job
              |
              v
OpenMetadata REST API
```

The ingestion Job uses the official image pinned to the same version as the
server. Connector code remains in that image and is not installed in the
normal Teoria Prefect worker.

## Development deployment

The `metadata` Compose profile contains only:

- OpenMetadata Server
- OpenMetadata PostgreSQL
- Elasticsearch
- the one-shot OpenMetadata schema migration

The `metadata-ingestion` profile exposes `openmetadata-ingestion-job`, a
one-shot `ingestion-base` container. Run it with both profiles enabled:

```bash
docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml \
  --profile metadata --profile metadata-ingestion \
  run --rm openmetadata-ingestion-job
```

The Job receives only the read-only Teoria Data DB credential and the
OpenMetadata ingestion bot token. Configuration is mounted read-only. It has
no published port and is removed after completion.

## Prefect execution boundary

The existing `teoria-ingestion` pool is a process pool and must not be granted
Docker socket access merely to run metadata ingestion. Development automation
must use a dedicated Docker work pool/worker. Production k3s automation must
use a dedicated Kubernetes work pool that creates an ephemeral Job from the
same pinned image.

The Prefect deployment owns:

- schedule and concurrency
- retry and timeout
- dependency ordering between metadata, lineage, usage, profile, and test jobs
- logs, notifications, and operational state

The OpenMetadata image owns:

- source connector execution
- connector-specific validation
- metadata, lineage, usage, profiler, and test workflow implementation
- writes to the OpenMetadata REST API

Do not install `openmetadata-ingestion` in `pipelines/Dockerfile`, duplicate its
connector logic in a Teoria Flow, or enable both OpenMetadata UI scheduling and
Prefect scheduling for the same workflow.

## UI consequences

Catalog exploration, descriptions, owners, tags, glossary terms, lineage, and
quality results remain available in OpenMetadata UI. Pipeline deployment,
scheduling, retry, and run operations are performed in Prefect UI. If a future
environment requires OpenMetadata UI-managed ingestion, use a separate
deployment mode with the OpenMetadata Kubernetes orchestrator; do not add
Airflow back to the default overlay.

## Workflow isolation

Metadata ingestion is the initial workflow. Profiler, query lineage, usage, and
data quality run as separate Jobs with independent schedules, permissions,
resource limits, and timeouts. A successful schema metadata ingestion should
not depend on profiler or query-log access.
