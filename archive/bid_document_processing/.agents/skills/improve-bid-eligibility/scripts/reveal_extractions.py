#!/usr/bin/env python3
"""Reveal pending fresh outputs only after matching source reviews are sealed."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reviews-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    root = args.manifest.parent
    failures = []
    for item in manifest["cases"]:
        if item["status"] != "completed_unrevealed":
            continue
        stem = f"{item['notice_number']}_{item['notice_order']}"
        review_path = args.reviews_dir / f"{stem}.json"
        seal_path = args.reviews_dir / f"{stem}.seal.json"
        if not review_path.exists() or not seal_path.exists():
            failures.append(f"{stem}:source_review_not_sealed")
            continue
        review_bytes = review_path.read_bytes()
        review = json.loads(review_bytes)
        seal = json.loads(seal_path.read_text())
        if hashlib.sha256(review_bytes).hexdigest() != seal.get("sha256"):
            failures.append(f"{stem}:source_review_changed_after_seal")
            continue
        source_input = root / item["source_input"]
        if hashlib.sha256(source_input.read_bytes()).hexdigest() != seal.get(
            "source_input_sha256"
        ):
            failures.append(f"{stem}:source_input_changed_after_review")
            continue
        if (review["notice"]["notice_number"], review["notice"]["notice_order"]) != (
            item["notice_number"], item["notice_order"],
        ):
            failures.append(f"{stem}:source_review_notice_mismatch")
            continue
        pending = root / item["pending_output"]
        output = root / f"{stem}.json"
        if output.exists():
            failures.append(f"{stem}:output_already_exists")
            continue
        os.chmod(pending, 0o600)
        pending.rename(output)
        item["status"] = "completed"
        item["output"] = output.name
        item["source_review"] = str(review_path)
        item["source_review_seal"] = str(seal_path)
        item.pop("pending_output", None)
    if failures:
        for failure in failures:
            print(failure)
        return 1
    manifest["revealed_at"] = datetime.now(timezone.utc).isoformat()
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
