#!/usr/bin/env python3
"""Run fresh bid-eligibility extraction for sampled notices without external writes."""

import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from teoria_pipelines.persistence import PostgresStore
from teoria_pipelines.settings import bootstrap_pipeline_settings
from teoria_pipelines.tasks.bid_eligibility import (
    EXTRACTION_VERSION,
    extract_bid_eligibility_notice,
)


def _keys(sample: dict) -> list[tuple[str, str]]:
    return [
        (str(item["notice_number"]), str(item["notice_order"]))
        for item in sample["candidates"]
    ]


def _safe_error_message(exc: Exception) -> str:
    """Retain actionable diagnostics without leaking URL query parameters or controls."""
    message = re.sub(r"https?://[^\s?]+\?[^\s]+", lambda match: (
        match.group(0).split("?", 1)[0] + "?<redacted>"
    ), str(exc))
    message = re.sub(r"[\x00-\x1f\x7f]+", " ", message).strip()
    return message[:300] or "no_message"


async def run(args: argparse.Namespace) -> int:
    sample = json.loads(args.sample.read_text())
    keys = _keys(sample)
    if args.max_cases is not None:
        keys = keys[:args.max_cases]
    settings = bootstrap_pipeline_settings()
    store = PostgresStore(settings.data_database_url or "")
    notices = store.list_notices_for_eligibility_extraction(
        len(keys), settings.bid_document_max_attempts,
        settings.bid_document_parse_max_attempts, notice_keys=keys,
    )
    by_key = {(item["notice_number"], item["notice_order"]): item for item in notices}
    sampled = {
        (str(item["notice_number"]), str(item["notice_order"])): item
        for item in sample["candidates"]
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "partition": args.partition,
        "sample_seed": sample.get("seed"),
        "extraction_version": EXTRACTION_VERSION,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "persist": False,
        "cases": [],
    }
    for number, order in keys:
        case = {
            "notice_number": number,
            "notice_order": order,
        }
        notice = by_key.get((number, order))
        if notice is None:
            metadata = sampled.get((number, order), {})
            case.update({
                "status": "not_extraction_ready",
                "error_class": (
                    "acquisition" if metadata.get("unavailable_count", 0) else "parsing"
                ),
                "document_count": metadata.get("document_count"),
                "unavailable_count": metadata.get("unavailable_count"),
                "unsupported_count": metadata.get("unsupported_count"),
            })
            manifest["cases"].append(case)
            continue
        try:
            evaluation = await extract_bid_eligibility_notice.fn(
                notice, persist=False, include_evaluation_input=True,
            )
        except Exception as exc:
            case.update({
                "status": "extraction_failed",
                "error_class": "extraction",
                "error_code": type(exc).__name__,
                "error_message": _safe_error_message(exc),
            })
            manifest["cases"].append(case)
            continue
        result = evaluation["extraction"]
        source_input = args.output_dir / f"{number}_{order}.source.json"
        source_input.write_text(
            json.dumps(evaluation["source_input"], ensure_ascii=False, indent=2) + "\n"
        )
        pending = args.output_dir / f".{number}_{order}.pending.json"
        pending.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        os.chmod(pending, 0)
        case.update({
            "status": "completed_unrevealed",
            "source_input": source_input.name,
            "pending_output": pending.name,
            "requirement_count": len(result["requirements"]),
            "unresolved_count": len(result["unresolved_candidates"]),
        })
        manifest["cases"].append(case)
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    return 1 if any(item["status"] != "completed_unrevealed"
                    for item in manifest["cases"]) else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--partition", choices=("discovery", "holdout"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-cases", type=int)
    args = parser.parse_args()
    if args.max_cases is not None and args.max_cases < 1:
        parser.error("--max-cases must be positive")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
