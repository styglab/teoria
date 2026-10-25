#!/usr/bin/env python3
"""Validate a proposal bundle and optionally submit pending suggestions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCHEMA_PATH = (
    (Path(__file__).resolve().parents[4] / '.agents/skills/enrich-metadata-asset') / "references/proposal_bundle.schema.json"
)


def validate(bundle: object) -> list[dict]:
    from jsonschema import Draft202012Validator, FormatChecker
    from jsonschema.exceptions import ValidationError

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(bundle)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "bundle"
        raise ValueError(f"{location}: {exc.message}") from None
    return bundle["suggestions"]


def submit(base_url: str, token: str | None, payload: dict) -> dict:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{base_url.rstrip('/')}/v1/admin/intelligence/suggestions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Admin API returned HTTP {exc.code}") from None
    except URLError as exc:
        raise RuntimeError(f"Admin API is unavailable: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--admin-base-url",
        default=os.environ.get(
            "TEORIA_ADMIN_BASE_URL", "http://localhost:8081/admin-api"
        ),
    )
    args = parser.parse_args()

    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    suggestions = validate(bundle)
    print(f"Validated {len(suggestions)} suggestion(s).")
    if not args.submit:
        print("Dry run only; nothing was submitted.")
        return 0

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    api_fields = schema["properties"]["suggestions"]["items"]["properties"].keys() - {
        "warnings"
    }
    token = os.environ.get("TEORIA_ADMIN_API_TOKEN")
    for item in suggestions:
        payload = {key: value for key, value in item.items() if key in api_fields}
        result = submit(args.admin_base_url, token, payload)
        suggestion_id = result.get("suggestion_id") or result.get("id") or "unknown"
        print(f"Submitted pending suggestion {suggestion_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
