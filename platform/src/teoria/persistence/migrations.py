from pathlib import Path

from teoria.persistence.postgres import connect


async def apply_migrations(database_url: str, migration_root: Path) -> list[str]:
    applied: list[str] = []
    async with connect(database_url, autocommit=True) as connection:
        await connection.execute("CREATE SCHEMA IF NOT EXISTS teoria")
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS teoria.schema_migrations "
            "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        existing = {
            row[0]
            async for row in (
                await connection.execute("SELECT version FROM teoria.schema_migrations")
            )
        }
        for path in sorted(migration_root.glob("*.sql")):
            if path.name in existing:
                continue
            async with connection.transaction():
                await connection.execute(path.read_text(encoding="utf-8"))
                await connection.execute(
                    "INSERT INTO teoria.schema_migrations (version) VALUES (%s)",
                    (path.name,),
                )
            applied.append(path.name)
    return applied
