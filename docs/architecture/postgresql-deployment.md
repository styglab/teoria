# PostgreSQL deployment boundaries

## Physical layout

Compose uses two PostgreSQL instances:

```text
postgres
└── teoria_data

platform-postgres
├── teoria_app
├── prefect
└── openmetadata_db
```

`teoria_data` is the Data Plane. It absorbs ingestion, backfill,
reconciliation, normalization, Runtime queries, and analytical reads. The
shared `platform-postgres` instance is the Control/Application Plane.

Sharing an instance does not merge ownership. Each Control database has its
own owner, password, migrations, connection URL, and `CONNECT` grant. Cross-
database SQL and direct reads of OpenMetadata tables are prohibited.

## Connection contracts

| Database | Role | Consumer |
|---|---|---|
| `teoria_data` | `teoria_pipeline` / `teoria_runtime` / `teoria_metadata` | Prefect writes, Runtime reads, OpenMetadata scans business schemas |

`teoria_metadata` has read access to the canonical `public_procurement` schema,
not the operational `ingestion` schema. Raw payloads, checkpoints, retry queues,
and pipeline audit tables are DataOps implementation state and are excluded from
the default business metadata catalog. If they need cataloging for platform
operations, register them later as a separate opt-in OpenMetadata service/domain
with separate access policy.
| `teoria_app` | `teoria_app` | Admin API and ontology/binding migrations |
| `prefect` | `prefect` | Prefect Server and background services |
| `openmetadata_db` | `openmetadata_user` | OpenMetadata Server and migrations |

Production configuration keeps four independent connection URLs even when
three URLs point to one PostgreSQL host. This allows Prefect or OpenMetadata to
move to a dedicated managed instance without an application schema migration.

## Migration procedure

When consolidating existing Control databases:

1. Stop Admin API, Prefect Server/services/workers, and OpenMetadata Server.
2. Create custom-format `pg_dump` archives for all three databases and record
   their SHA-256 checksums.
3. Start an empty PostgreSQL 17 `platform-postgres` volume.
4. Run `platform-postgres-init` to create the three roles and databases.
5. Restore each archive with ownership preserved.
6. Compare schema/table counts and exact counts for critical Prefect tables.
7. Start application migrations, Prefect, OpenMetadata, and Admin API against
   the new host.
8. Verify health, authentication, work pools, deployments, and database-role
   isolation.
9. Retain the old volumes and dump archives through the rollback window.

Do not use `docker compose down -v` during the rollback window.

## Rollback

Stop Control Plane writers, restore the previous connection hostnames, and
restart the old database containers with their original volumes. Any writes
accepted by `platform-postgres` after cutover must be reconciled before
rollback; therefore rollback should happen before normal operation resumes or
after taking a fresh dump from the new databases.

## Backup

Create a consistent set of logical custom-format archives for the Data Plane
and all three Control Plane databases:

```bash
TEORIA_BACKUP_ROOT=/secure/teoria-backups \
  deploy/compose/postgres/backup.sh
```

The script creates a UTC timestamp directory containing four `.dump` files,
the PostgreSQL server versions, and `SHA256SUMS`. It never deletes previous
backups. Store the directory outside the repository and Docker volumes, copy it
to durable encrypted storage, and test restore into disposable databases. A
backup is not considered operational until checksum verification and a restore
test have succeeded.

## Future split triggers

Move Prefect to a dedicated instance first when connection count, event/log
retention, vacuum, or I/O begins affecting `teoria_app` or OpenMetadata. Move
OpenMetadata separately when catalog ingestion, migration windows, or backup
policy requires an independent failure domain. No application model change is
required; only credentials and connection URLs change.
