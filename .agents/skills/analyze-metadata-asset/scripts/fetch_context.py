#!/usr/bin/env python3
"""Fetch a read-only OpenMetadata table view through the Teoria Admin API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-fqn", required=True)
    parser.add_argument("--admin-base-url", default="http://localhost:8001")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    base_url = args.admin_base_url.rstrip("/")
    url = f"{base_url}/v1/admin/metadata/tables/{quote(args.table_fqn, safe='')}"
    try:
        with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise SystemExit(f"Admin API returned HTTP {exc.code} for the requested table") from exc
    except URLError as exc:
        raise SystemExit(f"Admin API is unavailable: {exc.reason}") from exc

    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote metadata context to {args.output}")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
