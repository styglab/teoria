"""CLI commands for specification processing."""

import asyncio
import json

from teoria.domains.goods.contracts import SpecificationRun


def run_command(args):
    if args.specification_command == 'index-catalog':
        from teoria.domains.goods.data_processing.catalog.indexing import index_catalog
        if not 1 <= args.limit <= 1000:
            raise ValueError('limit must be between 1 and 1000')
        result = asyncio.run(index_catalog(args.limit))
        print(json.dumps(result))
        return 1 if result['failed_runs'] else 0
    if args.specification_command == 'dictionary-maintain':
        from teoria.domains.goods.normalization.legacy_dictionary.corpus_maintenance import maintain_dictionary
        result = asyncio.run(maintain_dictionary(json.loads(args.manifest.read_text())))
        summary={key:value for key,value in result.items() if key not in {'application','artifacts'}}
        summary['report']=next((ref['uri'] for ref in result['artifacts'] if ref['key'].endswith('/index.md')),None)
        print(json.dumps(summary,ensure_ascii=False,indent=2))
        return 1 if result['status']=='held' else 0
    if args.specification_command == "validate-graph":
        return _validate_graph(args)
    if args.specification_command == 'review-meanings':
        from teoria.domains.goods.normalization.meaning_proposals.meaning_review import MeaningReviewInput, prepare_meaning_review
        request = MeaningReviewInput.model_validate(json.loads(args.manifest.read_text()))
        result = asyncio.run(prepare_meaning_review(request, args.output_root))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result['summary']['held'] else 0
    if args.specification_command == "standard-workflow":
        return _run_standard_workflow(args)
    if args.specification_command == "evaluate":
        return _run_evaluation(args)
    return _run_processing(args)


def _validate_graph(args):
    import yaml
    from teoria.domains.goods.normalization.contracts.specification_graph import (
        DocumentGoodsGraphBatch, validate_graph_meanings,
    )

    try:
        batch = DocumentGoodsGraphBatch.model_validate(
            yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
        )
        meaning_reports = None
        if context_path := getattr(args, 'ontology_context', None):
            from teoria.platform.ontology.authoring.publication_contracts import PublishedOntologyContext
            context = PublishedOntologyContext.model_validate_json(context_path.read_bytes())
            meaning_reports = [validate_graph_meanings(graph, context) for graph in batch.graphs]
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(json.dumps({"status": "invalid", "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "status": "valid",
        "validation_scope": "structure_and_pinned_concept_references_only" if meaning_reports is not None else "structure_and_references_only",
        **({'meaning_references': meaning_reports} if meaning_reports is not None else {}),
        "documents": [{
            "document_id": g.document_id, "review_status": g.review_status,
            "subjects": len(g.subjects), "compositions": len(g.compositions),
            "item_relations": len(g.item_relations), "properties": len(g.properties),
            "requirements": len(g.requirements), "classifications": len(g.classifications),
        } for g in batch.graphs],
    }, ensure_ascii=False, indent=2))
    return 0


def _run_standard_workflow(args):
    from teoria.domains.goods.workflows.standard_authoring import (
        standard_workflow_flow,
    )
    from teoria.domains.goods.contracts import StandardWorkflow

    request = StandardWorkflow.model_validate(json.loads(args.manifest.read_text()))
    result = asyncio.run(standard_workflow_flow(request.model_dump(mode="json")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "failed" else 0


def _run_evaluation(args):
    from teoria.domains.goods.data_processing.evaluation.runner import (
        prepare_cycle,
        run_variant,
        finish_cycle,
        abort_cycle,
        discover_sources,
        cycle_status,
        compare_corpora,
    )

    step = args.evaluation_step
    if step == "schema":
        from teoria.domains.goods.data_processing.evaluation.cases import (
            EvaluationManifest,
        )

        print(
            json.dumps(
                EvaluationManifest.model_json_schema(), ensure_ascii=False, indent=2
            )
        )
        return 0
    if step == "discover":
        result = discover_sources(args.root, args.state_dir, args.limit)
    elif step == "status":
        result = cycle_status(args.state_dir)
    elif step == "quality-check":
        from teoria.domains.goods.data_processing.evaluation.runner import _state, _processor_revision
        from teoria.domains.goods.data_processing.evaluation.release_quality import check_release_quality
        state = _state(args.state_dir)
        if args.cycle_id not in state["cycles"]:
            raise ValueError("evaluation cycle not found")
        result = {"cycle_id": args.cycle_id, **check_release_quality(
            state["cycles"][args.cycle_id], _processor_revision())}
    elif step == "prepare":
        result = prepare_cycle(args.manifest, args.state_dir)
    elif step == "abort":
        result = abort_cycle(args.cycle_id, args.state_dir)
    elif step == "compare":
        result = compare_corpora(args.cycle_id, args.corpora, args.state_dir)
    elif step == "finish":
        result = asyncio.run(finish_cycle(args.cycle_id, args.state_dir))
    else:
        result = asyncio.run(run_variant(args.cycle_id, step, args.state_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("decision") == "rejected" or result.get("status") == "blocked" else 0


def _run_processing(args):
    from teoria.domains.goods.workflows.specifications import (
        standard_management_flow,
        document_processing_flow,
    )

    manifest = json.loads(args.manifest.read_text())
    if 'mode' not in manifest:
        from teoria.domains.goods.workflows.management_parameters import StandardManagementParameters
        parameters=StandardManagementParameters.model_validate(manifest)
        result=asyncio.run(standard_management_flow(manifest=parameters.model_dump(mode='json')))
        output=result.model_dump(mode='json') if hasattr(result,'model_dump') else result
        print(json.dumps(output,ensure_ascii=False,indent=2))
        return 1 if output['status'] in {'failed','held'} else 0
    request = SpecificationRun.model_validate(manifest)
    entry = (
        standard_management_flow
        if request.mode == "standard_management"
        else document_processing_flow
    )
    result = asyncio.run(entry(request.model_dump(mode="json")))
    print(result.model_dump_json(indent=2))
    return 1 if result.status == "failed" else 0
