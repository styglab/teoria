"""Offline CLI: freeze corpus/QA, evaluate structured retrieval, adapt with Harness2."""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path

from .codex_runner import CodexRunner
from .document_evidence import build_document_evidence
from .search_evaluation import (
    ANSWER_INSTRUCTION, EXTRACTION_INSTRUCTION, QA_INSTRUCTION, REVIEW_INSTRUCTION,
    METRIC_VERSION, QuestionSet, check_question_set, grade_answers, save_json, sha256, split_documents,
)


def load(path: Path):
    return json.loads(path.read_text())


def prepare(manifest: Path, exposed: Path, root: Path) -> None:
    if (root / "split.json").exists():
        raise ValueError("experiment is frozen; use another output directory")
    documents = load(manifest)["documents"]
    for doc in documents:
        for field, checksum in (("source_path", "source_sha256"), ("native_path", "native_sha256")):
            if sha256(Path(doc[field])) != doc[checksum]:
                raise ValueError(f"input hash mismatch: {doc['document_id']}")
    split = split_documents(documents, exposed_sha256={d["source_sha256"] for d in load(exposed)}, seed="teoria_specification_2026_10_20_v1")
    save_json(root / "split.json", split)
    (root / "baseline_prompt.md").write_text(EXTRACTION_INSTRUCTION)
    for subset in ("development", "validation"):
        for doc in split[subset]:
            evidence = build_document_evidence(load(Path(doc["native_path"])), document_id=doc["document_id"],
                parse_run_id="search_experiment", native_sha256=doc["native_sha256"])
            source = "\n".join(n.text for n in evidence.nodes if n.text.strip())
            save_json(root / "sources" / subset / f"{doc['document_id']}.json", {
                "document_id": doc["document_id"], "notice_number": doc["notice_number"],
                "source_sha256": doc["source_sha256"], "text": source,
                "parser_warnings": evidence.warnings, "unreadable_refs": evidence.unreadable_refs,
            })
    files = [root / "split.json", root / "baseline_prompt.md", *sorted((root / "sources").glob("*/*.json"))]
    save_json(root / "corpus_freeze.json", {str(p.relative_to(root)): sha256(p) for p in files})


def verify_corpus(root: Path) -> None:
    for name, checksum in load(root / "corpus_freeze.json").items():
        if sha256(root / name) != checksum:
            raise ValueError(f"frozen corpus changed: {name}")


async def make_questions(root: Path, runner: CodexRunner) -> None:
    verify_corpus(root)
    if (root / "freeze.json").exists():
        verify_freeze(root)
        return
    async def one(subset, path):
        source = load(path)
        output = root / "labels" / subset / path.name
        if output.exists():
            check_question_set(load(output), source["text"])
            return
        raw = await runner.generate(QA_INSTRUCTION, {"source": source, "schema": QuestionSet.model_json_schema()},
                                    root / "generation" / subset / path.name)
        checked = await runner.generate(REVIEW_INSTRUCTION, {"source": source, "proposal": raw,
                                       "schema": QuestionSet.model_json_schema()},
                                       root / "review" / subset / path.name)
        try:
            verified = check_question_set(checked, source["text"])
        except ValueError as error:
            checked = await runner.generate(REVIEW_INSTRUCTION, {"source": source, "proposal": checked,
                "validation_error": str(error), "schema": QuestionSet.model_json_schema()},
                root / "repair" / subset / path.name)
            verified = check_question_set(checked, source["text"])
        if len(verified.questions) != 6 or sum(q.expected is None for q in verified.questions) != 1:
            raise ValueError(f"expected five answerable and one unanswerable question: {path.stem}")
        save_json(output, verified.model_dump())
        print(f"QA {subset} {path.stem}: {len(verified.questions)}", flush=True)
    await asyncio.gather(*(one(subset, path) for subset in ("development", "validation")
                           for path in sorted((root / "sources" / subset).glob("*.json"))))
    files = sorted((root / "labels").glob("*/*.json")) + sorted((root / "sources").glob("*/*.json"))
    freeze = {str(p.relative_to(root)): sha256(p) for p in files}
    freeze["split.json"] = sha256(root / "split.json")
    save_json(root / "freeze.json", {"files": freeze, "label_status": "Codex-generated, independently Codex-reviewed silver; human_reviewed=false"})


def verify_freeze(root: Path) -> None:
    verify_corpus(root)
    for name, checksum in load(root / "freeze.json")["files"].items():
        if sha256(root / name) != checksum:
            raise ValueError(f"frozen file changed: {name}")
    split = load(root / "split.json")
    for subset in ("development", "validation"):
        for doc in split[subset]:
            source = load(root / "sources" / subset / f"{doc['document_id']}.json")
            if source["source_sha256"] != doc["source_sha256"]:
                raise ValueError("source identity changed")


def export_questions(root: Path) -> None:
    verify_freeze(root)
    fields = ["subset", "document_id", "question_id", "question", "category", "answerable",
              "owner", "attribute", "value", "unit", "operator", "configuration", "aggregation",
              "quote", "rationale", "label_status", "label_issue_status", "label_issue_reason"]
    issues = {i["case_id"]: i for i in load(root / "improvements.json").get("label_issues", [])} if (root / "improvements.json").exists() else {}
    with (root / "question_answers.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for path in sorted((root / "labels").glob("*/*.json")):
            for q in load(path)["questions"]:
                expected = q["expected"]
                issue = issues.get(f"{path.stem}/{q['question_id']}", {})
                writer.writerow({"subset": path.parent.name, "document_id": path.stem,
                    "question_id": q["question_id"], "question": q["question"], "category": q["category"],
                    "answerable": expected is not None, **(expected or {}), "rationale": q["rationale"],
                    "label_status": "codex_reviewed_silver; human_reviewed=false",
                    "label_issue_status": issue.get("status", ""), "label_issue_reason": issue.get("reason", "")})


async def predict(source: dict, questions: list[dict], runner: CodexRunner, directory: Path,
                  instruction: str = EXTRACTION_INSTRUCTION, dictionary: dict | None = None) -> dict:
    facts = await runner.generate(instruction, {"source": source}, directory / "facts.json")
    if dictionary is not None:
        from .search_dictionary import canonicalize_facts
        from .search_source_review import SOURCE_REVIEW_INSTRUCTION
        facts = await runner.generate(SOURCE_REVIEW_INSTRUCTION, {"source": source, "facts": facts}, directory / "reviewed_facts.json")
        facts, mappings = canonicalize_facts(facts, dictionary)
        save_json(directory / "canonical_facts.json", facts)
        save_json(directory / "attribute_mappings.json", mappings)
    answers = await runner.generate(ANSWER_INSTRUCTION, {"facts": facts, "questions": questions}, directory / "answers.json")
    # Retrieval must return an extracted record, not invent a second extraction.
    for answer in answers.get("answers", []):
        if isinstance(answer, dict) and answer.get("answer") is not None:
            if answer["answer"] not in facts.get("facts", []):
                answer["answer"] = {"provenance_error": "answer_not_in_extracted_facts"}
    return answers


async def evaluate(root: Path, runner: CodexRunner, *, subset: str, name: str, instruction: str,
                   dictionary: dict | None = None) -> dict:
    from .search_semantic_review import review_names
    verify_freeze(root)
    cases = []
    async def one(path):
        source = load(path)
        questions = check_question_set(load(root / "labels" / subset / path.name), source["text"])
        public = [{"question_id": q.question_id, "question": q.question} for q in questions.questions]
        answers = await predict(source, public, runner, root / "predictions" / name / subset / path.stem, instruction, dictionary)
        result = grade_answers(questions, answers, source["text"])
        answer_by_id = {a.get("question_id"): a.get("answer") for a in answers.get("answers", []) if isinstance(a, dict)}
        for q, row in zip(questions.questions, result["rows"], strict=True):
            if row["passed"] and q.expected is not None:
                cases.append({"case_id": f"{path.stem}/{q.question_id}", "question": q.question,
                              "expected": q.expected.model_dump(), "actual": answer_by_id[q.question_id]})
        print(f"{name} {subset} {path.stem} typed: {result['passed']}/{result['total']}", flush=True)
        return {"document_id": path.stem, **result}
    rows = await asyncio.gather(*(one(path) for path in sorted((root / "sources" / subset).glob("*.json"))))
    cases.sort(key=lambda c: c["case_id"])
    semantics = await review_names(cases, runner, root / "semantic_grades" / METRIC_VERSION / name / f"{subset}.json")
    for document in rows:
        for row in document["rows"]:
            judgement = semantics.get(f"{document['document_id']}/{row['question_id']}")
            if judgement:
                for field in ("owner_equivalent", "attribute_equivalent"):
                    if not judgement[field]:
                        row["failures"].append(field)
                row["semantic_review"] = judgement
                row["passed"] = not row["failures"]
        document["passed"] = sum(row["passed"] for row in document["rows"])
        document["metric"] = "source passage containment and typed match plus Codex owner/attribute equivalence review"
    total = sum(r["total"] for r in rows)
    result = {"name": name, "subset": subset, "metric_version": METRIC_VERSION,
              "total": total, "passed": sum(r["passed"] for r in rows), "documents": rows,
              "label_status": load(root / "freeze.json")["label_status"],
              "limitations": ["retrospective corpus split", "near-template leakage not audited", "same Codex backend creates/reviews labels, predicts and judges semantic names", "expected quotation containment may reject alternative valid passages", "numeric QA only; full ontology/search recall not measured"]}
    result["accuracy"] = result["passed"] / total if total else None
    print(f"{name} {subset} final: {result['passed']}/{total}", flush=True)
    save_json(root / "reports" / f"{name}_{subset}.json", result)
    return result


async def run(args) -> None:
    root = args.output.resolve()
    runner = CodexRunner(model=args.model, concurrency=args.concurrency)
    if args.action == "prepare":
        prepare(args.manifest, args.exposed, root)
    elif args.action == "questions":
        await make_questions(root, runner)
    elif args.action == "evaluate":
        instruction = args.prompt.read_text() if args.prompt else EXTRACTION_INSTRUCTION
        await evaluate(root, runner, subset=args.subset, name=args.name, instruction=instruction)
    elif args.action == "audit":
        from .search_improvements import find_improvements
        verify_freeze(root)
        await find_improvements(root, runner)
    elif args.action == "export":
        export_questions(root)


def complete_experiment(args) -> None:
    """Resume phases; select on development, lock selection, then open holdout labels."""
    from collections import Counter
    from .search_harness import adapt

    root = args.output.resolve()
    if not (root / "split.json").exists():
        if not args.manifest or not args.exposed:
            raise ValueError("first run requires --manifest and --exposed")
        prepare(args.manifest, args.exposed, root)
    def runner():
        return CodexRunner(model=args.model, concurrency=args.concurrency)
    asyncio.run(make_questions(root, runner()))
    export_questions(root)
    baseline_prompt = (root / "baseline_prompt.md").read_text()
    selection_path = root / "selection.json"
    if not selection_path.exists():
        if list((root / "reports").glob("*_validation.json")):
            raise ValueError("holdout was already opened; start a new version with a new holdout")
        baseline = asyncio.run(evaluate(root, runner(), subset="development", name="baseline", instruction=baseline_prompt))
        if not (root / "harness2/result.json").exists():
            adapt(root, model=args.model, tasks=args.tasks)
        adaptation = load(root / "harness2/result.json")
        if adaptation["failed"]:
            raise ValueError("Harness2 did not complete")
        best, chosen_name, chosen_prompt = baseline, "baseline", baseline_prompt
        candidates = sorted((root / "harness2/candidates").glob("*.md"))
        if not candidates:
            raise ValueError("no Harness2 candidate prompts")
        for path in candidates:
            report = asyncio.run(evaluate(root, runner(), subset="development", name=path.stem, instruction=path.read_text()))
            if report["passed"] > best["passed"]:
                best, chosen_name, chosen_prompt = report, path.stem, path.read_text()
        (root / "selected_prompt.md").write_text(chosen_prompt)
        save_json(selection_path, {"chosen": chosen_name, "development_passed": best["passed"],
                                  "baseline_development_passed": baseline["passed"],
                                  "prompt_sha256": sha256(root / "selected_prompt.md"),
                                  "development_reports": {p.name: sha256(p) for p in sorted((root / "reports").glob("*_development.json"))},
                                  "holdout_used_for_selection": False})
    selection = load(selection_path)
    if sha256(root / "selected_prompt.md") != selection["prompt_sha256"]:
        raise ValueError("selected prompt changed after selection")
    for name, checksum in selection["development_reports"].items():
        if sha256(root / "reports" / name) != checksum:
            raise ValueError("development evidence changed after selection")
    selected_prompt = (root / "selected_prompt.md").read_text()
    from .search_improvements import find_improvements
    asyncio.run(find_improvements(root, runner()))
    export_questions(root)
    from .search_dictionary import build_dictionary
    from .search_source_review import review_development
    reviewed_name = asyncio.run(review_development(root, selection["chosen"], runner()))
    dictionary = asyncio.run(build_dictionary(root, reviewed_name, runner()))
    # Reuse source extraction while grading the complete prompt + dictionary path.
    import shutil
    for path in (root / "predictions" / selection["chosen"] / "development").glob("*/facts.json"):
        target = root / "predictions/selected_dictionary/development" / path.parent.name / "facts.json"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            shutil.copy2(path.with_suffix(".receipt.json"), target.with_suffix(".receipt.json"))
        reviewed = root / "source_review/development" / path.parent.name / "reviewed_facts.json"
        reviewed_target = target.parent / "reviewed_facts.json"
        if not reviewed_target.exists():
            shutil.copy2(reviewed, reviewed_target)
            shutil.copy2(reviewed.with_suffix(".receipt.json"), reviewed_target.with_suffix(".receipt.json"))
    selected_development = asyncio.run(evaluate(root, runner(), subset="development", name="selected_dictionary",
                                                instruction=selected_prompt, dictionary=dictionary))
    lock = {"prompt_sha256": selection["prompt_sha256"], "dictionary_sha256": sha256(root / "dictionary/draft.json"),
            "development_report_sha256": sha256(root / "reports/selected_dictionary_development.json"),
            "code_sha256": {p.name: sha256(p) for p in (Path(__file__).parent / name for name in (
                "search_evaluation.py", "search_semantic_review.py", "search_dictionary.py", "search_source_review.py"))}}
    if (root / "pipeline_lock.json").exists() and load(root / "pipeline_lock.json") != lock:
        raise ValueError("pipeline changed after holdout lock")
    save_json(root / "pipeline_lock.json", lock)
    baseline_validation = asyncio.run(evaluate(root, runner(), subset="validation", name="baseline", instruction=baseline_prompt))
    selected_validation = asyncio.run(evaluate(root, runner(), subset="validation", name="selected",
                                               instruction=selected_prompt, dictionary=dictionary))
    dev = selected_development
    failures = Counter(f for document in dev["documents"] for row in document["rows"] for f in row["failures"])
    save_json(root / "report.json", {
        "split": {key: len(load(root / "split.json")[key]) for key in ("development", "validation")},
        "questions": sum(len(load(p)["questions"]) for p in (root / "labels").glob("*/*.json")),
        "dictionary": {"properties": len(dictionary["properties"]), "held_groups": len(dictionary["held_groups"]),
                       "status": dictionary["status"], "source_subset": "development"},
        "selection": selection, "baseline_validation": baseline_validation,
        "selected_development": selected_development, "pipeline_lock": lock,
        "selected_validation": selected_validation, "development_remaining_failures": dict(failures),
        "validation_improved": selected_validation["passed"] > baseline_validation["passed"],
        "ontology_approval": "unapproved; QA results do not publish or approve ontology",
        "next_updates": [f"Investigate {key}: {count} development failures" for key, count in failures.most_common()],
        "holdout_policy": "report only; do not tune using validation failures",
        "backend": "Codex CLI; no Qwen fallback",
        "harness2_commit": "1cfe254e8d25b15f37048c3730134686abe60335",
        "attribute_mapping_counts": dict(Counter(mapping["status"] for p in
            (root / "predictions/selected").glob("validation/*/attribute_mappings.json") for mapping in load(p))),
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "questions", "evaluate", "adapt", "audit", "export", "run"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--exposed", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--subset", choices=["development", "validation"], default="development")
    parser.add_argument("--name", default="baseline")
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--tasks", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    if args.action == "run":
        complete_experiment(args)
    elif args.action == "adapt":
        from .search_harness import adapt
        adapt(args.output.resolve(), model=args.model, tasks=args.tasks)
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
