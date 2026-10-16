import argparse

from teoria.persistence import apply_migrations
from teoria.settings import Settings


async def run_migrate_app(args: argparse.Namespace, settings: Settings) -> int:
    if not settings.app_database_url:
        print("ERROR TEORIA_APP_DATABASE_URL is required")
        return 1
    for version in await apply_migrations(settings.app_database_url, args.migrations):
        print(f"Applied {version}")
    return 0
