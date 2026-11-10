"""Operational specification flows: ordered tasks, immutable artifacts, final DB checkpoint."""

import asyncio
from pathlib import Path
import hashlib
from prefect import flow
from prefect import task
from prefect.cache_policies import NO_CACHE
from teoria.domains.goods.contracts import ArtifactRef
from teoria.domains.goods.contracts import RunResult
from teoria.domains.goods.contracts import SpecificationRun
from teoria.domains.goods.contracts import StandardReference
from teoria.domains.goods.data_processing.storage.run_repository import (
    SpecificationRepository,
)
from teoria.domains.goods.workflows import tasks
from teoria.domains.goods.data_processing.flows import extract_documents
from teoria.domains.goods.data_processing.storage.processing_workspace import (
    processing_workspace,
)
from teoria.domains.goods.workflows.processing_status import processing_stages
from teoria.domains.goods.workflows.management_parameters import (
    StandardManagementParameters,
    DocumentSelection,
    DictionaryManagement,
    ManagementExecution,
)


from teoria.domains.goods.processor_revision import processing_revision as processor_revision


@task(name="규격 처리 실행 시작", persist_result=False, cache_policy=NO_CACHE)
async def start_execution(request: SpecificationRun):
    await verify_application_release(request)
    if request.ontology_alignment is not None:
        from teoria.domains.goods.authoring_client import GoodsAuthoringClient
        from teoria.domains.goods.normalization.meaning_proposals.ontology_context import (
            load_published_context,
        )

        async with GoodsAuthoringClient() as api:
            await load_published_context(
                request.ontology_alignment, api, standard=request.standard
            )
    fingerprint = hashlib.sha256(
        (request.input_fingerprint() + processor_revision()).encode()
    ).hexdigest()
    return await SpecificationRepository.from_environment().start(request, fingerprint)


async def verify_application_release(request: SpecificationRun):
    """CLI and workers verify approval before registering a run or reading originals."""
    if request.application_release_id is None:
        return
    import json
    from teoria.domains.goods.authoring_client import GoodsAuthoringClient
    from teoria.domains.goods.normalization.processing_criteria_validation import (
        require_application_rules,
    )
    from teoria.domains.goods.data_processing.storage.artifact_store import read_uri

    async with GoodsAuthoringClient() as api:
        release = await api.application_standard(request.application_release_id)
    if (
        release.get("status") != "approved"
        or request.mode != "document_processing"
        or request.standard is None
        or request.dictionary_standard is None
        or release.get("standard_ref") != request.standard.model_dump(mode="json")
        or release.get("dictionary_ref")
        != request.dictionary_standard.model_dump(mode="json")
        or release.get("classification_code") != request.classification_code
        or request.dictionary_auto_approve
        or request.dictionary_meaning_auto_approve
    ):
        raise ValueError("application_standard_reference_mismatch")
    raw = await read_uri(request.standard.uri)
    if hashlib.sha256(raw).hexdigest() != request.standard.sha256:
        raise ValueError("application_standard_checksum_mismatch")
    readiness = require_application_rules(json.loads(raw))
    if readiness["standard_kind"] != release.get("standard_kind") or readiness[
        "classification_code"
    ] != release.get("classification_code"):
        raise ValueError("application_standard_reference_mismatch")


@task(name="규격 처리 완료 체크포인트", persist_result=False, cache_policy=NO_CACHE)
async def complete_execution(result: RunResult):
    await SpecificationRepository.from_environment().complete(result)


@task(name="규격 처리 실패 기록", persist_result=False, cache_policy=NO_CACHE)
async def fail_execution(run_id, error_code):
    await SpecificationRepository.from_environment().fail(run_id, error_code)


async def finalize_application_standard(request, result):
    if (
        request.mode != "standard_management"
        or not request.auto_approve_application_standard
        or result.status == "failed"
        or result.summary.get("automatic_application_standard", {}).get("status")
        == "approved"
    ):
        return result
    from teoria.domains.goods.workflows.processing_criteria_approval import (
        approve_application_standard,
    )

    return await approve_application_standard(request, result)


async def execute_specification_run(
    request: SpecificationRun, *, extra_artifacts=(), extra_summary=None
):
    initial_revision = processor_revision()
    replay = await start_execution(request)
    if replay is not None:
        return await finalize_application_standard(request, replay)
    try:
        quality_evaluation = await tasks.verify_quality_evaluation(request, initial_revision)
        async with processing_workspace(
            request.artifact_root, request.run_id, "processing"
        ) as working:
            temporary = str(working.path)
            # Clients, parser output and model responses never outlive this workspace.
            extracted_ref, reused = await extract_documents(request, temporary)  # 01–05
            dictionary = await tasks.resolve_dictionary(
                request, temporary, extracted_ref
            )  # 06
            dictionary_summary = (
                dictionary["summary"]
                if dictionary
                else {"status": "skipped", "reason": "expression_dictionary_disabled"}
            )
            alignment = (
                await tasks.align_with_ontology(
                    request, temporary, extracted_ref, dictionary
                )
                if request.ontology_alignment is not None
                else None
            )
            selection = await tasks.select_and_map_standard(
                request,
                temporary,
                extracted_ref,
                dictionary,
                **({"ontology_alignment": alignment} if alignment else {}),
            )  # 07
            normalized = await tasks.load(Path(temporary) / "normalized.json")
            report_ref = await tasks.persist_report(
                request, temporary, normalized["standard_version"]
            )  # 08
            document_refs = await tasks.persist_document_results(
                request, temporary
            )  # 09
            corpus = await tasks.load(Path(temporary) / "extracted.json")
            work = await tasks.load(Path(temporary) / "work.json")
            references = [
                *extra_artifacts,
                *([quality_evaluation["artifact"]] if quality_evaluation else []),
                *document_refs,
                *(e["artifact"] for e in work),
                extracted_ref,
                *(dictionary["artifacts"] if dictionary else []),
                *(alignment["artifacts"] if alignment else []),
                *selection["artifacts"],
                report_ref,
            ]
            revision = processor_revision()
            if revision != initial_revision:
                raise ValueError("processor changed during specification execution")
            receipt_ref = await tasks.persist_execution_receipt(
                request, temporary, revision, references, quality_evaluation
            )
            from teoria.domains.goods.workflows.processing_quality import (
                processing_quality,
            )

            quality = processing_quality(
                request, corpus, normalized["summary"], revision
            )
            document_results = []
            for d in corpus["documents"]:
                state = (
                    "partial"
                    if d.get("extraction_status") == "partial"
                    else "extracted"
                )
                document_results.append(
                    {
                        "document_id": d["document_id"],
                        "notice_number": d.get("notice_number"),
                        "status": state,
                        "source_sha256": d["source"]["sha256"],
                        "result_summary": {
                            "entities": len(d["entities"]),
                            "relations": len(d["relations"]),
                            "attributes": len(d["attributes"]),
                            "quarantined_attributes": len(
                                d.get("quarantined_attributes", [])
                            ),
                            "quality": d.get("unresolved_extraction", {}),
                            "parser_version": d["parser"]["version"],
                            "dictionary_contexts": [
                                {k: v for k, v in stamp.items() if k != "document_id"}
                                for stamp in (dictionary or {}).get(
                                    "context_stamps", []
                                )
                                if stamp["document_id"] == d["document_id"]
                            ],
                        },
                    }
                )
            for d in corpus["unavailable_documents"]:
                document_results.append(
                    {
                        "document_id": d["document_id"],
                        "notice_number": d.get("notice_number"),
                        "status": "excluded"
                        if d.get("disposition") == "excluded"
                        else "failed",
                        "source_sha256": d["source"]["sha256"],
                        "result_summary": {
                            k: d[k]
                            for k in (
                                "stage",
                                "reason",
                                "code",
                                "details",
                                "disposition",
                            )
                            if k in d
                        },
                    }
                )
            partial = (
                any(
                    d.get("disposition") != "excluded"
                    for d in corpus["unavailable_documents"]
                )
                or any(d["status"] == "partial" for d in document_results)
                or any(
                    normalized.get(key, {}).get("automatically_deferred", 0) > 0
                    for key in ["summary", "entity_summary", "relation_summary"]
                )
            )
            partial = (
                partial
                or dictionary_summary.get("held", 0) > 0
                or dictionary_summary.get("proposed", 0) > 0
            )
            semantic_summary = dictionary_summary.get("semantic_authoring", {})
            partial = (
                partial
                or semantic_summary.get("held", 0) > 0
                or semantic_summary.get("proposed", 0) > 0
            )
            partial = (
                partial
                or (dictionary or {}).get("meaning_summary", {}).get("held", 0) > 0
            )
            all_excluded = bool(corpus["unavailable_documents"]) and all(
                d.get("disposition") == "excluded"
                for d in corpus["unavailable_documents"]
            )
            state = (
                "completed"
                if all_excluded
                else "failed"
                if not corpus["documents"]
                else "partial"
                if partial
                else "completed"
            )
            diagnostics = await working.publish()
            result = RunResult(
                run_id=request.run_id,
                status=state,
                artifacts=sorted(
                    [
                        ArtifactRef.model_validate(a)
                        for a in [*references, *diagnostics, receipt_ref]
                    ],
                    key=lambda a: a.key,
                ),
                document_results=sorted(
                    document_results, key=lambda d: d["document_id"]
                ),
                standard=StandardReference.model_validate(selection["standard"]),
                summary={
                    "documents": len(corpus["documents"]),
                    "failed_documents": sum(
                        d.get("disposition") != "excluded"
                        for d in corpus["unavailable_documents"]
                    ),
                    "excluded_documents": sum(
                        d.get("disposition") == "excluded"
                        for d in corpus["unavailable_documents"]
                    ),
                    "attributes": sum(
                        len(d["attributes"]) for d in corpus["documents"]
                    ),
                    **normalized["summary"],
                    "entity_normalization": normalized.get("entity_summary", {}),
                    "relation_normalization": normalized.get("relation_summary", {}),
                    "human_approval_required": bool(
                        alignment and alignment["report"]["summary"]["observations"]
                    ),
                    "reused_extraction": reused,
                    "processor_revision": revision,
                    "application_release_id": str(request.application_release_id)
                    if request.application_release_id
                    else None,
                    "execution_receipt": {
                        "uri": receipt_ref["uri"],
                        "sha256": receipt_ref["sha256"],
                    },
                    "quality_evaluation": quality_evaluation or "not_attached",
                    "quality": quality,
                    "dictionary": dictionary_summary,
                    "dictionary_operation_id": dictionary["result"]["operation_id"]
                    if dictionary
                    else None,
                    **(
                        {
                            "ontology_alignment": {
                                "mode": "comparison_only",
                                "authority": "suggestion",
                                "auto_applied": False,
                                **alignment["report"]["summary"],
                            }
                        }
                        if alignment
                        else {}
                    ),
                    **(extra_summary or {}),
                    "processing_stages": processing_stages(
                        request, corpus, dictionary, normalized, alignment
                    ).model_dump(mode="json"),
                },
            )
            # This is the only success/partial checkpoint: every referenced object exists first.
            await complete_execution(result)
            return await finalize_application_standard(request, result)
    except BaseException as exc:
        try:
            await asyncio.shield(fail_execution(request.run_id, type(exc).__name__))
        except Exception:
            pass  # Preserve the processing error; no credentials or raw response are logged.
        raise


@flow(name="procurement-standard-management", persist_result=False, log_prints=False)
async def standard_management_flow(
    manifest: dict | None = None,
    classification_code: str | None = None,
    target_specifications: int = 30,
    selection: DocumentSelection = DocumentSelection(),
    management: DictionaryManagement = DictionaryManagement(),
    execution: ManagementExecution = ManagementExecution(),
):
    if manifest is not None and (
        classification_code is not None
        or target_specifications != 30
        or selection != DocumentSelection()
        or management != DictionaryManagement()
        or execution != ManagementExecution()
    ):
        raise ValueError("use either manifest or the individual parameters, not both")
    if manifest is not None and "mode" in manifest:
        request = SpecificationRun.model_validate(manifest)
        if request.mode != "standard_management":
            raise ValueError("mode must be standard_management")
        return await execute_specification_run(request)
    from teoria.domains.goods.workflows.management_batch import execute_management_batch

    parameters = StandardManagementParameters.model_validate(
        manifest
        if manifest is not None
        else {
            "classification_code": classification_code,
            "target_specifications": target_specifications,
            "selection": selection,
            "management": management,
            "execution": execution,
        }
    )
    return await execute_management_batch(parameters)


@flow(name="procurement-document-processing", persist_result=False, log_prints=False)
async def document_processing_flow(manifest: dict):
    request = SpecificationRun.model_validate(manifest)
    if request.mode != "document_processing":
        raise ValueError("mode must be document_processing")
    return await execute_specification_run(request)
