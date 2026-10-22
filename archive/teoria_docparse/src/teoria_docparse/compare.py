"""Differential runner: agreement with kordoc is not accuracy against original documents."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import statistics
import subprocess
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from .models import Diagnostic, ParseResult
from .version import __version__


def normalized_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"</?(?:sup|sub|u|b|i|strong|em)(?:\s[^>]*)?>", "", value)
    value = re.sub(r"<br\s*/?>", "\n", value)
    value = re.sub(r"\\([\\`*_{}\[\]()#+.!$|<>-])", r"\1", value)
    return "".join(unicodedata.normalize("NFC", value).split())


def block_text(blocks: list[dict]) -> str:
    parts = []
    for block in blocks:
        table = block.get("table")
        if table:
            for _, _, cell in anchors(table):
                parts.append(block_text(cell["blocks"]) if cell.get("blocks") else cell.get("text", ""))
        elif block.get("type") != "image":
            parts.append(block.get("text") or "")
        if block.get("children"):
            parts.append(block_text(block["children"]))
    return "\n".join(parts)


def anchors(table: dict):
    covered = set()
    for r, row in enumerate(table.get("cells", [])):
        for c, cell in enumerate(row):
            if (r, c) in covered or cell.get("covered"):
                continue
            rs = cell.get("row_span", cell.get("rowSpan", 1))
            cs = cell.get("col_span", cell.get("colSpan", 1))
            covered.update(
                (rr, cc) for rr in range(r, r + rs) for cc in range(c, c + cs) if (rr, cc) != (r, c)
            )
            yield r, c, cell


def tables_in_order(blocks: list[dict]) -> list[dict]:
    tables = []
    for block in blocks:
        if block.get("table"):
            tables.append(block["table"])
            for _, _, cell in anchors(block["table"]):
                tables.extend(tables_in_order(cell.get("blocks", [])))
        tables.extend(tables_in_order(block.get("children", [])))
    return tables


def table_signature(table: dict, with_text: bool) -> tuple:
    cells = []
    for row, col, cell in anchors(table):
        item = (
            row,
            col,
            cell.get("row_span", cell.get("rowSpan", 1)),
            cell.get("col_span", cell.get("colSpan", 1)),
        )
        if with_text:
            item += (normalized_text(cell.get("text", "")),)
        cells.append(item)
    return table.get("rows"), table.get("cols"), tuple(cells)


def compare_results(reference: dict, candidate: dict) -> dict:
    left = normalized_text(block_text(reference.get("blocks", [])))
    right = normalized_text(block_text(candidate.get("blocks", [])))
    overlap = sum((Counter(left) & Counter(right)).values())
    precision = overlap / len(right) if right else float(not left)
    recall = overlap / len(left) if left else float(not right)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    ref_tables, py_tables = (
        tables_in_order(reference.get("blocks", [])),
        tables_in_order(candidate.get("blocks", [])),
    )
    matched_grid = sum(
        table_signature(a, False) == table_signature(b, False) for a, b in zip(ref_tables, py_tables)
    )
    matched_cells = sum(
        table_signature(a, True) == table_signature(b, True) for a, b in zip(ref_tables, py_tables)
    )
    all_grids = len(ref_tables) == len(py_tables) and matched_grid == len(ref_tables)
    all_cells = len(ref_tables) == len(py_tables) and matched_cells == len(ref_tables)
    both_success = reference.get("success", False) and candidate.get("success", False)
    return {
        "reference_success": reference.get("success", False),
        "python_success": candidate.get("success", False),
        "reference_error": reference.get("code"),
        "python_error": candidate.get("error_code"),
        "reference_characters": len(left),
        "python_characters": len(right),
        "has_comparable_text": bool(left and right),
        "text_equal_normalized": left == right,
        "character_multiset_precision": round(precision, 6),
        "character_multiset_recall": round(recall, 6),
        "character_multiset_f1": round(f1, 6),
        "reading_order_similarity": 1.0
        if left == right
        else round(SequenceMatcher(None, left, right, autojunk=False).ratio(), 6),
        "reference_tables": len(ref_tables),
        "python_tables": len(py_tables),
        "paired_grid_matches": matched_grid,
        "paired_grid_and_cell_text_matches": matched_cells,
        "all_table_grids_equal": all_grids,
        "all_tables_and_cells_equal": all_cells,
        "observed_agreement": both_success and left == right and all_cells,
        "python_warning_codes": sorted({w["code"] for w in candidate.get("warnings", [])}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare native Python parsing with pinned kordoc on identical bytes"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--reference-package", type=Path, required=True)
    parser.add_argument("--pdf-backend", choices=("pymupdf",), default="pymupdf", help=argparse.SUPPRESS)
    parser.add_argument("--reference-version", default="4.22.15")
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--node", default="node")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--document-timeout", type=int, default=120)
    args = parser.parse_args()
    output = args.output.resolve()
    # Refuse reuse: a new comparison must not overwrite the previous evidence.
    output.mkdir(parents=True, exist_ok=False)
    documents = json.loads(args.manifest.read_text(encoding="utf-8"))
    ids = [d["document_id"] for d in documents]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-zA-Z0-9_]+", str(i)) for i in ids):
        parser.error("Manifest requires unique path-safe document IDs")
    for doc in documents:
        path = Path(doc["source_path"])
        if not path.is_absolute():
            path = args.manifest.resolve().parent / path
        doc["source_path"] = str(path.resolve())
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
            parser.error(f"Input checksum mismatch: {doc['document_id']}")
    config = {
        "pdf_backend": args.pdf_backend,
        "reference_package": str(args.reference_package.resolve()),
        "reference_version": args.reference_version,
        "output": str(output),
        "documents": documents,
        "candidate_source_sha256": source_digest(),
    }
    config_path = output / "run_config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        subprocess.run(
            [args.node, str(args.bridge.resolve()), str(config_path)],
            check=True,
            capture_output=True,
            timeout=args.timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        # Do not forward process logs, which may contain private document content.
        (output / "runner_error.json").write_text(
            json.dumps({"stage": "reference", "type": type(error).__name__})
        )
        print("Reference execution failed; see runner_error.json", file=sys.stderr)
        return 2
    reference_runs = {r["document_id"]: r for r in json.loads((output / "reference_runs.json").read_text())}
    rows = []
    for doc in documents:
        dest = output / doc["document_id"]
        native = dest / "python.json"
        seconds = None
        try:
            worker = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "teoria_docparse.cli",
                    doc["source_path"],
                    "--output",
                    str(native),
                    "--pdf-backend",
                    args.pdf_backend,
                ],
                capture_output=True,
                timeout=args.document_timeout,
                check=False,
            )
            if worker.returncode not in (0, 1) or not native.exists():
                raise RuntimeError("Candidate process failed")
            seconds = json.loads(worker.stdout)["parse_seconds"]
            candidate = json.loads(native.read_text(encoding="utf-8"))
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, KeyError) as error:
            code = "TIMEOUT" if isinstance(error, subprocess.TimeoutExpired) else "CANDIDATE_EXCEPTION"
            candidate = ParseResult(
                False, doc["format"], error_code=code, warnings=[Diagnostic(code, type(error).__name__)]
            ).to_dict()
            native.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
        reference = json.loads((dest / "reference.json").read_text())
        row = {
            "document_id": doc["document_id"],
            "format": doc["format"],
            "input_sha256": doc["sha256"],
            "python_seconds": round(seconds, 6) if seconds is not None else None,
            "reference_seconds": round(reference_runs[doc["document_id"]]["seconds"], 6),
            "reference_output_sha256": reference_runs[doc["document_id"]]["sha256"],
            "python_output_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
            **compare_results(reference, candidate),
        }
        rows.append(row)
        print(
            json.dumps(
                {
                    "document_id": row["document_id"],
                    "agreement": row["observed_agreement"],
                    "character_f1": row["character_multiset_f1"],
                }
            ),
            flush=True,
        )
    summary = {
        "schema_version": "1",
        "python_version": sys.version.split()[0],
        "candidate_version": __version__,
        "pdf_backend": args.pdf_backend,
        "reference_version": args.reference_version,
        "candidate_source_sha256": config["candidate_source_sha256"],
        "documents": len(rows),
        "ocr": False,
        "observed_agreement_documents": sum(r["observed_agreement"] for r in rows),
        "mean_character_multiset_f1": round(
            statistics.mean(r["character_multiset_f1"] for r in rows if r["has_comparable_text"]), 6
        )
        if any(r["has_comparable_text"] for r in rows)
        else None,
        "interpretation": "Agreement with reference output, not independent accuracy. One timed execution per document; no speed ranking.",
        "results": rows,
    }
    (output / "comparison.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Python / kordoc differential comparison",
        "",
        f"Reference: kordoc {args.reference_version}; Python: {__version__}; OCR: off.",
        "",
        "Agreement measures output fidelity to the reference, not correctness against the source document.",
        "",
        "| ID | Format | Reference/Python success | Char multiset F1 | Reading order | Tables reference/Python | Equal grids | Equal grid+cell text |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['document_id']} | {row['format']} | {row['reference_success']}/{row['python_success']} | "
            f"{row['character_multiset_f1']:.4f} | {row['reading_order_similarity']:.4f} | "
            f"{row['reference_tables']}/{row['python_tables']} | {row['all_table_grids_equal']} | {row['all_tables_and_cells_equal']} |"
        )
    (output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if source_digest() != config["candidate_source_sha256"]:
        raise RuntimeError("Candidate implementation changed during comparison; discard this run")
    return 0


def source_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*")):
        if path.suffix in (".py", ".json"):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
