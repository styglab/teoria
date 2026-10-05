from pathlib import Path

import psycopg


def apply_migrations(database_url: str, migration_root: Path) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS teoria")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS teoria.schema_migrations "
            "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        existing = {row[0] for row in connection.execute("SELECT version FROM teoria.schema_migrations")}
        for path in sorted(migration_root.glob("*.sql")):
            if path.name in existing:
                continue
            with connection.transaction():
                connection.execute(path.read_text(encoding="utf-8"))
                connection.execute("INSERT INTO teoria.schema_migrations (version) VALUES (%s)", (path.name,))
            applied.append(path.name)
    return applied
