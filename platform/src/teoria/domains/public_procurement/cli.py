import argparse
import json

import psycopg

from teoria.domains.public_procurement.data_profile import run_data_profile
from teoria.domains.public_procurement.identity_validation import (
    validate_procurement_identity,
)
from teoria.settings import Settings


async def run_validate_ontology_shadow(
    args: argparse.Namespace, settings: Settings
) -> int:
    if not settings.admin_data_database_url:
        print("ERROR TEORIA_ADMIN_DATA_DATABASE_URL is required")
        return 1
    try:
        result = await validate_procurement_identity(
            settings.admin_data_database_url,
            args.bid_notice_id,
        )
    except (ValueError, LookupError, psycopg.Error) as exc:
        print(f"ERROR ontology_shadow_validation_failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["status"] in {"passed", "partial"} else 1


async def run_profile_ontology_sources(
    args: argparse.Namespace, settings: Settings
) -> int:
    if not settings.admin_data_database_url:
        print("ERROR TEORIA_ADMIN_DATA_DATABASE_URL is required")
        return 1
    if args.statement_timeout_ms < 1:
        print("ERROR --statement-timeout-ms must be positive")
        return 1
    try:
        report = await run_data_profile(
            settings.admin_data_database_url,
            include_deep=args.deep,
            statement_timeout_ms=args.statement_timeout_ms,
        )
    except psycopg.Error as exc:
        print(f"ERROR ontology_source_profile_failed: {exc}")
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0
