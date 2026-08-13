#!/usr/bin/env python3
"""Create a sanitized evaluation-case skeleton without reading production content."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--partition", choices=("discovery", "regression", "holdout"), required=True)
    parser.add_argument("--notice-number", required=True)
    parser.add_argument("--notice-order", required=True)
    parser.add_argument("--work-type")
    parser.add_argument("--input", type=Path, help="sanitized exact model-input JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = args.input.read_bytes() if args.input else b"case-skeleton"
    case = {
        "case_id": args.case_id,
        "partition": args.partition,
        "notice": {
            "notice_number": args.notice_number,
            "notice_order": args.notice_order,
            "work_type": args.work_type,
        },
        "provenance": {
            "sampled_at": datetime.now(timezone.utc).isoformat(),
            "input_fingerprint": f"sha256:{hashlib.sha256(payload).hexdigest()}",
            "versions": {},
            "expectation_method": "independent_source_review",
            "document_checksums": [],
        },
        "expected": {
            "requirements": [],
            "unresolved_candidates": [],
            "adjudication_required": False,
        },
        "classification": {
            "earliest_layer": "none",
            "severity": "none",
            "error_codes": [],
            "adjudication_note": None,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
