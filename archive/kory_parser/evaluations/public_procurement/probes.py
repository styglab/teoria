"""Source-derived partial oracles; fragment presence is not complete document accuracy."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from kory_parser.compare import anchors, block_text, normalized_text, tables_in_order

from ..runner import sha, write_json


def tag(node: Element):
    return node.tag.rsplit("}", 1)[-1]


def source_labels(manifest, reviewed):
    """Read XML directly; never read parser output to construct an oracle."""
    cases = []
    for item in manifest:
        source = Path(item["source_path"])
        if sha(source.read_bytes()) != item["sha256"]:
            raise ValueError("Source label input changed")
        case = {key: item[key] for key in ["document_id", "sha256", "format", "split"]}
        if item["format"] in {"docx", "hwpx"}:
            fragments = []
            count = 0
            parts = []
            with zipfile.ZipFile(source) as archive:
                for name in archive.namelist():
                    if not (
                        name == "word/document.xml"
                        or name.startswith("Contents/section")
                        and name.endswith(".xml")
                    ):
                        continue
                    if archive.getinfo(name).file_size > 50 * 1024 * 1024:
                        raise ValueError("Source XML exceeds review budget")
                    xml = ElementTree.fromstring(archive.read(name))
                    if any(tag(n).lower() in {"del", "deletebegin", "deleteend"} for n in xml.iter()):
                        raise ValueError("Tracked revisions require separate source review")
                    parts.append(name)
                    fragments.extend("".join(n.itertext()) for n in xml.iter() if tag(n) == "t")
                    count += sum(tag(n) == "tbl" for n in xml.iter())
            case.update(
                source_fragments=sorted({s for s in fragments if len(normalized_text(s)) >= 3}),
                table_count=count,
                evidence={"kind": "original_xml", "parts": parts},
            )
            cases.append(case)
        elif item["format"] == "xlsx":
            values = []
            parts = []
            with zipfile.ZipFile(source) as archive:
                strings = []
                if "xl/sharedStrings.xml" in archive.namelist():
                    strings = [
                        "".join(n.text or "" for n in x.iter() if tag(n) == "t")
                        for x in ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                    ]
                for name in archive.namelist():
                    if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
                        continue
                    parts.append(name)
                    xml = ElementTree.fromstring(archive.read(name))
                    for cell in xml.iter():
                        if tag(cell) != "c":
                            continue
                        value = next((n.text or "" for n in cell if tag(n) == "v"), "")
                        kind = cell.get("t")
                        if kind == "s" and value:
                            value = strings[int(value)]
                        elif kind == "inlineStr":
                            value = "".join(n.text or "" for n in cell.iter() if tag(n) == "t")
                        elif kind == "b" and value:
                            value = "TRUE" if value == "1" else "FALSE"
                        if value:
                            values.append(value)
            case.update(cell_values=values, evidence={"kind": "original_cached_xml_values", "parts": parts})
            cases.append(case)
        elif item["document_id"] in reviewed:
            record = reviewed[item["document_id"]]
            if record["sha256"] != item["sha256"] or not record.get("evidence"):
                raise ValueError("Reviewed source identity/evidence mismatch")
            case.update(record)
            cases.append(case)
    return {
        "schema_version": 1,
        "cases": cases,
        "interpretation": "Partial original-XML and manually rendered-page checks; no whole-document accuracy claim. No parser output was used as an oracle.",
    }


def semantic_value(value):
    text = normalized_text(value)
    try:
        number = Decimal(text.replace(",", "").removesuffix("%"))
        if not number.is_finite():
            return text
        if text.endswith("%"):
            number /= 100
        return ("number", number.normalize())
    except InvalidOperation:
        return ("text", text)


def table_blocks(blocks):
    for block in blocks:
        if block.get("table"):
            yield block
            for _, _, cell in anchors(block["table"]):
                yield from table_blocks(cell.get("blocks", []))
        yield from table_blocks(block.get("children", []))


def grade(case, actual):
    checks = {}
    if "source_fragments" in case:
        text = normalized_text(block_text(actual.get("blocks", [])))
        fragments = case["source_fragments"]
        checks["source_fragment_presence"] = {
            "passed": sum(normalized_text(s) in text for s in fragments),
            "total": len(fragments),
        }
    tables = tables_in_order(actual.get("blocks", []))
    if "table_count" in case:
        checks["xml_table_count"] = {"passed": int(len(tables) == case["table_count"]), "total": 1}
    if "cell_values" in case:
        expected = Counter(semantic_value(v) for v in case["cell_values"])
        observed = Counter(
            semantic_value(cell.get("text", ""))
            for t in tables
            for _, _, cell in anchors(t)
            if cell.get("text", "")
        )
        checks["cached_cell_value_presence"] = {
            "passed": sum((expected & observed).values()),
            "total": sum(expected.values()),
        }
    if "pdf_pages" in case:
        blocks = list(table_blocks(actual.get("blocks", [])))
        count_correct = grid_correct = 0
        for page in case["pdf_pages"]:
            page_tables = [
                b["table"]
                for b in blocks
                if b.get("pageNumber", (b.get("source") or {}).get("page")) == page["page"]
            ]
            count_correct += len(page_tables) == page["table_count"]
            grid_correct += len(page_tables) == 1 and (page_tables[0]["rows"], page_tables[0]["cols"]) == (
                page["rows"],
                page["cols"],
            )
        checks["reviewed_pdf_page_table_count"] = {"passed": count_correct, "total": len(case["pdf_pages"])}
        checks["reviewed_pdf_page_grid"] = {"passed": grid_correct, "total": len(case["pdf_pages"])}
    return checks


def score_benchmark(labels, benchmark_dir):
    report = json.loads((benchmark_dir / "benchmark.json").read_text())
    identifiers = {r["document_id"]: r for r in report["results"]}
    results = []
    totals = {e: {} for e in ["baseline", "candidate", "kordoc"]}
    for case in labels["cases"]:
        if identifiers[case["document_id"]]["sha256"] != case["sha256"]:
            raise ValueError("Source oracle and benchmark input mismatch")
        row = {"document_id": case["document_id"], "split": case["split"], "engines": {}}
        for engine, total_metrics in totals.items():
            path = benchmark_dir / case["document_id"] / (engine + ".json")
            actual = json.loads(path.read_text()) if path.exists() else {"success": False, "blocks": []}
            checks = grade(case, actual)
            row["engines"][engine] = checks
            for name, counts in checks.items():
                total = total_metrics.setdefault(name, {"passed": 0, "total": 0})
                for key in ["passed", "total"]:
                    total[key] += counts[key]
        results.append(row)
    for metrics in totals.values():
        for counts in metrics.values():
            counts["rate"] = counts["passed"] / counts["total"] if counts["total"] else None
    regressions = []
    improvements = []
    for row in results:
        for name, before in row["engines"]["baseline"].items():
            after = row["engines"]["candidate"][name]
            if before["passed"] > after["passed"]:
                regressions.append(f"{row['document_id']}:{name}")
            elif before["passed"] < after["passed"]:
                improvements.append(f"{row['document_id']}:{name}")
    return {
        "schema_version": 1,
        "benchmark_manifest_sha256": report["manifest_sha256"],
        "benchmark_source_hashes": report["source_hashes"],
        "labelled_documents": len(results),
        "totals": totals,
        "results": results,
        "regressions": regressions,
        "improvements": improvements,
        "interpretation": labels["interpretation"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.labels.exists():
        labels = json.loads(args.labels.read_text())
    else:
        labels = source_labels(json.loads(args.manifest.read_text()), json.loads(args.reviewed.read_text()))
        write_json(args.labels, labels)
    if args.benchmark:
        if not args.output or args.output.exists():
            raise ValueError("New output required")
        result = score_benchmark(labels, args.benchmark)
        result["labels_sha256"] = sha(args.labels.read_bytes())
        write_json(args.output, result)
        print(
            json.dumps(
                {
                    "labelled_documents": result["labelled_documents"],
                    "totals": result["totals"],
                    "regressions": result["regressions"],
                    "improvements": result["improvements"],
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
