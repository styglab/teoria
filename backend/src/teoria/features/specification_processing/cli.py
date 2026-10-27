"""CLI commands for specification processing."""

import asyncio
import json

from teoria.features.specification_processing.models import SpecificationRun


def run_command(args):
    if args.specification_command == "validate-graph":
        return _validate_graph(args)
    if args.specification_command == "standard-workflow":
        return _run_standard_workflow(args)
    if args.specification_command == "evaluate":
        return _run_evaluation(args)
    return _run_processing(args)


def _validate_graph(args):
    import yaml
    from teoria.features.goods_normalization.contracts.specification_graph import (
        DocumentGoodsGraphBatch,
    )

    try:
        batch = DocumentGoodsGraphBatch.model_validate(
            yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(json.dumps({"status": "invalid", "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "status": "valid",
        "validation_scope": "structure_and_references_only",
        "documents": [{
            "document_id": g.document_id, "review_status": g.review_status,
            "subjects": len(g.subjects), "compositions": len(g.compositions),
            "item_relations": len(g.item_relations), "properties": len(g.properties),
            "requirements": len(g.requirements), "classifications": len(g.classifications),
        } for g in batch.graphs],
    }, ensure_ascii=False, indent=2))
    return 0


def _run_standard_workflow(args):
    from teoria.features.specification_processing.standard_workflow import (
        standard_workflow_flow,
    )
    from teoria.features.specification_processing.models import StandardWorkflow

    request = StandardWorkflow.model_validate(json.loads(args.manifest.read_text()))
    result = asyncio.run(standard_workflow_flow(request.model_dump(mode="json")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "failed" else 0


def _run_evaluation(args):
    from teoria.features.specification_processing.evaluation import (
        prepare_cycle,
        run_variant,
        finish_cycle,
        abort_cycle,
    )

    step = args.evaluation_step
    if step == "schema":
        from teoria.features.specification_processing.evaluation_cases import (
            EvaluationManifest,
        )

        print(
            json.dumps(
                EvaluationManifest.model_json_schema(), ensure_ascii=False, indent=2
            )
        )
        return 0
    if step == "prepare":
        result = prepare_cycle(args.manifest, args.state_dir)
    elif step == "abort":
        result = abort_cycle(args.cycle_id, args.state_dir)
    elif step == "finish":
        result = asyncio.run(finish_cycle(args.cycle_id, args.state_dir))
    else:
        result = asyncio.run(run_variant(args.cycle_id, step, args.state_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("decision") == "rejected" else 0


def _run_processing(args):
    from teoria.features.specification_processing.flows import (
        standard_management_flow,
        document_processing_flow,
    )

    manifest = json.loads(args.manifest.read_text())
    request = SpecificationRun.model_validate(manifest)
    entry = (
        standard_management_flow
        if request.mode == "standard_management"
        else document_processing_flow
    )
    result = asyncio.run(entry(request.model_dump(mode="json")))
    print(result.model_dump_json(indent=2))
    return 1 if result.status == "failed" else 0
