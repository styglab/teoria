"""Same-byte, repeated warm-parse benchmark with explicitly configured OCR of Kory snapshots and kordoc."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

from .execution import run_process
from .runner import PROJECT, sha, tree_digest, write_json

PYTHON_WORKER = """
import json,sys,time
from pathlib import Path
from kory_parser import parse,ParseOptions
from kory_parser.version import __version__
c=json.load(sys.stdin)
data=Path(c['source']).read_bytes()
supported='recover_numbered_structure' in getattr(ParseOptions,'__dataclass_fields__',{})
extra={'recover_numbered_structure':c.get('numbered_structure',False)} if supported else {}
options=ParseOptions(ocr=c.get('ocr',False),images=False,**extra)
parse(data,options)
seconds=[]
for _ in range(c['repetitions']):
 start=time.perf_counter()
 result=parse(data,options)
 seconds.append(time.perf_counter()-start)
Path(c['output']).write_text(json.dumps(result.to_dict(),ensure_ascii=False))
Path(c['measurement']).write_text(json.dumps({'seconds':seconds,'version':__version__,'options':{'ocr':options.ocr,'images':False,'numbered_structure_requested':c.get('numbered_structure',False),'numbered_structure_supported':supported}}))
"""


def benchmark(
    manifest_path, baseline, reference, output, *, repetitions=3, timeout=90, candidate=PROJECT, ocr=False, numbered_structure=False
):
    if repetitions < 1 or timeout <= 0:
        raise ValueError("Positive repetitions and timeout required")
    output.mkdir(parents=True, exist_ok=False)
    documents = json.loads(manifest_path.read_text())
    if not documents:
        raise ValueError("Empty benchmark manifest")
    source_hashes = {
        name: tree_digest(root / "src") for name, root in [("baseline", baseline), ("candidate", candidate)]
    }
    reference_version = json.loads((reference / "package.json").read_text())["version"]
    rows = []
    for index, item in enumerate(documents):
        source = Path(item["source_path"])
        if sha(source.read_bytes()) != item["sha256"]:
            raise ValueError("Benchmark input checksum mismatch")
        directory = output / item["document_id"]
        directory.mkdir()
        # Alternate order to reduce systematic ordering bias.
        engines = (
            ["baseline", "candidate", "kordoc"] if index % 2 == 0 else ["kordoc", "candidate", "baseline"]
        )
        row = {
            key: item[key] for key in ["document_id", "format", "sha256", "split", "family"] if key in item
        }
        row["engines"] = {}
        for engine in engines:
            parsed = directory / (engine + ".json")
            measured = directory / (engine + "_measurement.json")
            config = {
                "source": str(source.resolve()),
                "output": str(parsed.resolve()),
                "measurement": str(measured.resolve()),
                "format": item["format"],
                "repetitions": repetitions,
                "ocr": ocr,
                "numbered_structure": numbered_structure,
                "reference_package": str(reference.resolve()),
                "reference_version": reference_version,
            }
            started = time.monotonic()
            try:
                if engine == "kordoc":
                    cfg = directory / "reference_config.json"
                    write_json(cfg, config)
                    run = run_process(
                        ["node", str(PROJECT / "evaluations/reference_worker.mjs"), str(cfg.resolve())],
                        cwd=PROJECT,
                        timeout=timeout,
                    )
                else:
                    root = baseline if engine == "baseline" else candidate
                    run = run_process(
                        [sys.executable, "-c", PYTHON_WORKER],
                        cwd=root,
                        env=dict(os.environ, PYTHONPATH=str(root / "src")),
                        timeout=timeout,
                        input=json.dumps(config),
                    )
                (directory / (engine + "_stderr.log")).write_text(run.stderr)
                (directory / (engine + "_stdout.log")).write_text(run.stdout)
                if run.returncode or not parsed.exists() or not measured.exists():
                    raise RuntimeError("Benchmark worker failed")
                measurement = json.loads(measured.read_text())
                actual = json.loads(parsed.read_text())
                row["engines"][engine] = {
                    **measurement,
                    "median_seconds": statistics.median(measurement["seconds"]),
                    "success": actual.get("success", False),
                    "error_code": actual.get("error_code", actual.get("code")),
                    "output_sha256": sha(parsed.read_bytes()),
                    "execution_error": None,
                }
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
                row["engines"][engine] = {
                    "success": False,
                    "error_code": "EXECUTION_FAILED",
                    "execution_error": type(error).__name__,
                    "median_seconds": None,
                }
            row["engines"][engine]["worker_wall_seconds"] = time.monotonic() - started
        rows.append(row)
        write_json(output / "progress.json", rows)
        print(
            json.dumps(
                {
                    "document_id": item["document_id"],
                    "format": item["format"],
                    "success": {key: value["success"] for key, value in row["engines"].items()},
                }
            ),
            flush=True,
        )
    if source_hashes != {
        name: tree_digest(root / "src") for name, root in [("baseline", baseline), ("candidate", candidate)]
    }:
        raise ValueError("Benchmark sources changed during execution")
    report = {
        "schema_version": 1,
        "manifest_sha256": sha(manifest_path.read_bytes()),
        "manifest_path": str(manifest_path.resolve()),
        "source_hashes": source_hashes,
        "reference_version": reference_version,
        "reference_package_sha256": tree_digest(reference),
        "repetitions": repetitions,
        "warmups": 1,
        "ocr": ocr,
        "images": False,
        "numbered_structure": numbered_structure,
        "results": rows,
        "interpretation": "Warm in-memory parsing; worker startup and file reading excluded. Quality requires independent source checks.",
    }
    write_json(output / "benchmark.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=PROJECT)
    parser.add_argument("--reference-package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--ocr", action="store_true", help="Enable OCR explicitly for both engines")
    parser.add_argument("--numbered-structure", action="store_true")
    args = parser.parse_args()
    benchmark(
        args.manifest.resolve(),
        args.baseline.resolve(),
        args.reference_package.resolve(),
        args.output.resolve(),
        repetitions=args.repetitions,
        timeout=args.timeout,
        candidate=args.candidate.resolve(),
        ocr=args.ocr,
        numbered_structure=args.numbered_structure,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
