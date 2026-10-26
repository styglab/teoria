"""Summarize one immutable sampling, repair and acceptance cycle."""

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

from kory_parser.compare import block_text, normalized_text

from ..runner import sha, write_json

ENGINES = ("baseline", "candidate", "kordoc")


def generate(
    root,
    output,
    *,
    sample_name="sample",
    benchmark_name="benchmark",
    quality_name="quality.json",
    labels_name="source_labels.json",
    cleanup_intermediates=True,
):
    output.mkdir(parents=True, exist_ok=False)
    sample = json.loads((root / sample_name / "sampling.json").read_text())
    benchmark = json.loads((root / benchmark_name / "benchmark.json").read_text())
    quality = json.loads((root / quality_name).read_text())
    acceptance = json.loads((root / "acceptance/acceptance.json").read_text())
    if quality["benchmark_manifest_sha256"] != benchmark["manifest_sha256"]:
        raise ValueError("Quality/benchmark manifest identity mismatch")
    if sha((root / labels_name).read_bytes()) != quality["labels_sha256"]:
        raise ValueError("Source labels changed after grading")
    common = [row for row in benchmark["results"] if all(row["engines"][e]["success"] for e in ENGINES)]
    total = {e: sum(row["engines"][e]["median_seconds"] for row in common) for e in ENGINES}
    success = {e: sum(row["engines"][e]["success"] for row in benchmark["results"]) for e in ENGINES}
    versions = {
        engine: sorted(
            {
                row["engines"][engine]["version"]
                for row in benchmark["results"]
                if row["engines"][engine].get("version")
            }
        )
        for engine in ENGINES
    }
    agreement = {e: [] for e in ["baseline", "candidate"]}
    for row in common:
        directory = root / benchmark_name / row["document_id"]
        ref = normalized_text(
            block_text(json.loads((directory / "kordoc.json").read_text()).get("blocks", []))
        )
        for engine, values in agreement.items():
            actual = normalized_text(
                block_text(json.loads((directory / (engine + ".json")).read_text()).get("blocks", []))
            )
            overlap = sum((Counter(ref) & Counter(actual)).values())
            values.append(2 * overlap / (len(ref) + len(actual)) if ref or actual else 1)
    report = {
        "schema_version": 1,
        "sampled_documents": sample["sampled_count"],
        "compared_documents": len(benchmark["results"]),
        "formats": sample["formats"],
        "splits": sample["splits"],
        "success": success,
        "timing_common_documents": len(common),
        "warm_median_sum_seconds": total,
        "reference_version": benchmark["reference_version"],
        "versions": versions,
        "candidate_time_reduction_vs_baseline": 1 - total["candidate"] / total["baseline"],
        "candidate_time_reduction_vs_kordoc": 1 - total["candidate"] / total["kordoc"],
        "reference_agreement_mean_character_f1": {
            e: statistics.mean(values) for e, values in agreement.items()
        },
        "source_quality": quality["totals"],
        "source_reviewed_documents": quality["labelled_documents"],
        "acceptance": acceptance,
        "manifest_sha256": benchmark["manifest_sha256"],
        "source_labels_sha256": quality["labels_sha256"],
        "limitations": [
            "Partial source checks, not full-document accuracy.",
            "Source checks rely on original XML or explicitly recorded review evidence; no independent human review is implied.",
            "Warm timing from this sample and host, not a universal performance ranking.",
            "Memory and OCR accuracy were not measured.",
            "Inspected validation documents are future regression data, not a fresh blind test.",
        ],
    }
    write_json(output / "summary.json", report)
    lines = [
        "# Kory Parser public-document improvement cycle",
        "",
        f"Fresh sample: {sample['sampled_count']} documents from {sample['notice_frame_count']} notices; formats: {sample['formats']}. Compared documents including replays: {len(benchmark['results'])}.",
        f"Kory baseline {', '.join(versions['baseline'])}; candidate {', '.join(versions['candidate'])}; kordoc {benchmark['reference_version']}. OCR/images disabled.",
        "",
        "| Check | Kory before | Kory after | kordoc |",
        "|---|---:|---:|---:|",
        "| Execution success | "
        + " | ".join(f"{success[e]}/{len(benchmark['results'])}" for e in ENGINES)
        + " |",
        "| Common-success warm median sum (seconds) | "
        + " | ".join(f"{total[e]:.6f}" for e in ENGINES)
        + " |",
    ]
    for metric in quality["totals"]["baseline"]:
        counts = [quality["totals"][e][metric] for e in ENGINES]
        lines.append(
            "| "
            + metric
            + " | "
            + " | ".join(f"{v['passed']}/{v['total']} ({v['rate']:.4%})" for v in counts)
            + " |"
        )
    lines += [
        "",
        f"Time reduction vs baseline: {report['candidate_time_reduction_vs_baseline']:.2%}; vs kordoc: {report['candidate_time_reduction_vs_kordoc']:.2%}.",
        "Reference character multiset agreement (not independent accuracy): "
        + str(report["reference_agreement_mean_character_f1"]),
        "",
        f"Accepted: {acceptance['accepted']}; applied: {acceptance['applied']}; tests passed: {acceptance['tests_passed']}.",
        f"Changed sample documents: {acceptance['changed_documents']}; historical regression: {acceptance.get('historical_regression')}.",
        "",
        "The seven PDF page checks belong to one reviewed cost-schedule document; they are not seven independent documents.",
    ]
    lines += [""] + ["- " + limit for limit in report["limitations"]]
    (output / "summary.md").write_text("\n".join(lines) + "\n")
    if cleanup_intermediates:
        from .cleanup import cleanup_cycle

        cleanup = cleanup_cycle(root, apply=True)
        write_json(output / "cleanup_summary.json", cleanup)
    print(
        json.dumps(
            {
                k: report[k]
                for k in [
                    "sampled_documents",
                    "warm_median_sum_seconds",
                    "candidate_time_reduction_vs_baseline",
                ]
            }
        )
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample", default="sample")
    parser.add_argument("--benchmark", default="benchmark")
    parser.add_argument("--quality", default="quality.json")
    parser.add_argument("--labels", default="source_labels.json", help="Frozen labels filename within the cycle")
    parser.add_argument("--keep-intermediates", action="store_true")
    args = parser.parse_args()
    generate(
        args.cycle_root.resolve(),
        args.output.resolve(),
        sample_name=args.sample,
        benchmark_name=args.benchmark,
        quality_name=args.quality,
        labels_name=args.labels,
        cleanup_intermediates=not args.keep_intermediates,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
