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

The repository builds a thin `teoria-openmetadata-ingestion` image from that
official image. It adds only the non-secret workflow YAML. Baking the workflow
avoids host bind-path differences between the Compose client and Docker daemon;
credentials are still injected only at runtime.

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

Compose provides the opt-in `metadata-orchestration` profile and the dedicated
`teoria-metadata` process pool. Only `prefect-metadata-worker` receives the
Docker socket. The normal ingestion and AI workers cannot launch containers.
Because the Docker socket is host-privileged, this profile is for a trusted
single-host development deployment only. Kubernetes must use its API and a
namespaced ServiceAccount instead of mounting a container-runtime socket.

The deployment is isolated in `pipelines/prefect.metadata.yaml`, so it is only
registered when the `metadata-orchestration` profile is enabled. Generate a
dedicated least-privilege OpenMetadata ingestion-bot token and set
`OPENMETADATA_INGESTION_BOT_TOKEN` before starting that profile. Its daily
05:00 Asia/Seoul schedule is active once registered.

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
