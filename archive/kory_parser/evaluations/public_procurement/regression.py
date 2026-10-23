"""Replay the fixed corpus against frozen baseline and candidate parser sources."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..execution import run_process
from ..runner import sha, tree_digest, write_json
from .gate import canonical


def replay(manifest_path, baseline, candidate, output, *, timeout=90, seconds=900):
    manifest = json.loads(manifest_path.read_text())
    if not manifest or timeout <= 0 or seconds <= 0:
        raise ValueError("Nonempty corpus and positive budgets required")
    identifiers = [r["document_id"] for r in manifest]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Duplicate regression IDs")
    output.mkdir(parents=True, exist_ok=False)
    hashes = {"baseline": tree_digest(baseline / "src"), "candidate": tree_digest(candidate / "src")}
    started = time.monotonic()
    rows = []
    status = "error"
    try:
        for item in manifest:
            source = Path(item["source_path"])
            if not source.is_absolute():
                source = manifest_path.parent / source
            if sha(source.read_bytes()) != item["sha256"]:
                raise ValueError("Regression input changed")
            directory = output / item["document_id"]
            directory.mkdir()
            for name, root in [("baseline", baseline), ("candidate", candidate)]:
                parsed = directory / (name + ".json")
                if name == "candidate" and hashes["baseline"] == hashes["candidate"]:
                    shutil.copyfile(directory / "baseline.json", parsed)
                    continue
                remaining = seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("Regression budget exhausted")
                run = run_process(
                    [
                        sys.executable,
                        "-m",
                        "kory_parser.cli",
                        str(source.resolve()),
                        "-o",
                        str(parsed.resolve()),
                    ],
                    cwd=root,
                    env=dict(os.environ, PYTHONPATH=str(root / "src")),
                    timeout=min(timeout, remaining),
                )
                (directory / (name + "_stderr.log")).write_text(run.stderr)
                if run.returncode not in [0, 1] or not parsed.exists():
                    raise ValueError("Regression worker failed")
            before = json.loads((directory / "baseline.json").read_text())
            after = json.loads((directory / "candidate.json").read_text())
            rows.append(
                {
                    "document_id": item["document_id"],
                    "input_sha256": item["sha256"],
                    "equal_except_version": canonical(before) == canonical(after),
                    "before_success": before["success"],
                    "after_success": after["success"],
                }
            )
            write_json(output / "progress.json", rows)
        status = "complete"
    except (TimeoutError, subprocess.TimeoutExpired):
        status = "time_budget"
    finally:
        current = {"baseline": tree_digest(baseline / "src"), "candidate": tree_digest(candidate / "src")}
        if hashes != current:
            status = "source_changed"
        report = {
            "schema_version": 1,
            "status": status,
            "manifest_sha256": sha(manifest_path.read_bytes()),
            "baseline_source_sha256": hashes["baseline"],
            "candidate_source_sha256": hashes["candidate"],
            "documents": len(manifest),
            "processed_documents": len(rows),
            "equal_except_version": sum(r["equal_except_version"] for r in rows),
            "results": rows,
            "identical_sources_reused": hashes["baseline"] == hashes["candidate"],
            "elapsed_seconds": time.monotonic() - started,
        }
        write_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--seconds", type=float, default=900)
    args = parser.parse_args()
    result = replay(
        args.manifest.resolve(),
        args.baseline.resolve(),
        args.candidate.resolve(),
        args.output.resolve(),
        timeout=args.timeout,
        seconds=args.seconds,
    )
    print(json.dumps({k: result[k] for k in ["status", "documents", "equal_except_version"]}))
    return (
        0 if result["status"] == "complete" and result["documents"] == result["equal_except_version"] else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
