"""Explicit offline goods notice recovery; no schedules or provider requests."""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from teoria.features.goods_notice_collection.backup_restore import (
    BackupManifest,
    restore_backup,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument(
        "--database-url-env", default="TEORIA_TEST_GOODS_RESTORE_DATABASE_URL"
    )
    args = parser.parse_args()
    last = 0.0

    def progress(data):
        nonlocal last
        if time.monotonic() - last >= 20 or data["phase"] != "stage":
            print(json.dumps(data), flush=True)
            last = time.monotonic()

    try:
        manifest = BackupManifest(**json.loads(args.manifest.read_text()))
        result = asyncio.run(
            restore_backup(
                os.environ[args.database_url_env],
                args.subset,
                manifest,
                expected_database=args.expected_database,
                progress=progress,
            )
        )
    except Exception as error:  # noqa: BLE001 -- sanitize errors at the process boundary
        # DB errors may include raw payloads or URLs. Keep them out of CLI logs.
        print(
            f"Recovery failed ({type(error).__name__}); transaction rolled back if opened.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
