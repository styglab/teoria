#!/usr/bin/env python3
"""Validate a proposal bundle and optionally submit pending suggestions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TARGET_TYPES = {
    "openmetadata_table", "openmetadata_column", "openmetadata_glossary", "ontology",
}
SUGGESTION_TYPES = {
    "description", "binding", "glossary_term", "glossary_term_assignment",
    "ontology_change", "test_suite", "quality_test",
}
RISK_LEVELS = {"low", "medium", "high"}
REQUIRED = {
    "target_type", "target_ref", "suggestion_type", "proposed_value", "confidence",
    "risk_level", "model_provider", "model_name", "policy_version", "evidence",
}
API_FIELDS = REQUIRED | {"rationale", "model_version"}


def validate(bundle: object) -> list[dict]:
    if not isinstance(bundle, dict) or bundle.get("bundle_version") != "1.0":
        raise ValueError("bundle_version must be '1.0'")
    suggestions = bundle.get("suggestions")
    if not isinstance(suggestions, list) or not suggestions:
        raise ValueError("suggestions must be a non-empty array")
    for index, item in enumerate(suggestions):
        label = f"suggestions[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be an object")
        missing = REQUIRED - item.keys()
        if missing:
            raise ValueError(f"{label} is missing: {', '.join(sorted(missing))}")
        if item["target_type"] not in TARGET_TYPES:
            raise ValueError(f"{label}.target_type is invalid")
        expected_prefix = {
            "openmetadata_table": "openmetadata://table/",
            "openmetadata_column": "openmetadata://column/",
            "openmetadata_glossary": "openmetadata://glossary/",
            "ontology": "teoria://ontology/",
        }[item["target_type"]]
        if not isinstance(item["target_ref"], str) or not item["target_ref"].startswith(expected_prefix):
            raise ValueError(f"{label}.target_ref must start with {expected_prefix}")
        if item["suggestion_type"] not in SUGGESTION_TYPES:
            raise ValueError(f"{label}.suggestion_type is invalid")
        if not isinstance(item["proposed_value"], dict):
            raise ValueError(f"{label}.proposed_value must be an object")
        if item["suggestion_type"] == "description" and item["target_type"] == "openmetadata_column":
            required_column_fields = {
                "description", "table_id", "column_name", "column_fqn",
                "source_version", "source_description",
            }
            missing_column_fields = required_column_fields - item["proposed_value"].keys()
            if missing_column_fields:
                raise ValueError(
                    f"{label}.proposed_value is missing column application fields: "
                    f"{', '.join(sorted(missing_column_fields))}"
                )
        confidence = item["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError(f"{label}.confidence must be between 0 and 1")
        if item["risk_level"] not in RISK_LEVELS:
            raise ValueError(f"{label}.risk_level is invalid")
        if item["policy_version"] != "metadata-asset-analysis-v1":
            raise ValueError(f"{label}.policy_version is invalid")
        if not isinstance(item["evidence"], list) or not item["evidence"]:
            raise ValueError(f"{label}.evidence must be non-empty")
        for evidence_index, evidence in enumerate(item["evidence"]):
            if not isinstance(evidence, dict) or not evidence.get("evidence_type") or not evidence.get("source_ref"):
                raise ValueError(f"{label}.evidence[{evidence_index}] requires evidence_type and source_ref")
    return suggestions


def submit(base_url: str, token: str | None, payload: dict) -> dict:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{base_url.rstrip('/')}/v1/admin/intelligence/suggestions",
        data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Admin API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Admin API is unavailable: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--admin-base-url", default="http://localhost:8001")
    args = parser.parse_args()

    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    suggestions = validate(bundle)
    print(f"Validated {len(suggestions)} suggestion(s).")
    if not args.submit:
        print("Dry run only; nothing was submitted.")
        return 0

    token = os.environ.get("TEORIA_ADMIN_API_TOKEN")
    for item in suggestions:
        payload = {key: value for key, value in item.items() if key in API_FIELDS}
        result = submit(args.admin_base_url, token, payload)
        suggestion_id = result.get("suggestion_id") or result.get("id") or "unknown"
        print(f"Submitted pending suggestion {suggestion_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
