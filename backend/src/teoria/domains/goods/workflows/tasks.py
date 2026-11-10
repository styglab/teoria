"""Prefect task boundaries for specification I/O, IE stages and canonical artifacts."""

from __future__ import annotations
import asyncio
import hashlib
import json
from pathlib import Path
from prefect import task
from teoria.domains.goods.data_processing.storage.artifact_store import (
    artifact_store,
    read_uri,
)
from teoria.domains.goods.contracts import SpecificationRun, StandardArtifact
from teoria.domains.goods.authoring_client import GoodsAuthoringClient

from teoria.domains.goods.data_processing.tasks import (
    TASK_OPTIONS,
    load,
    save,
    run_key,
    runner,
)


@task(name="06 표준 사전 관리·연결", **TASK_OPTIONS)
async def resolve_dictionary(
    request: SpecificationRun, workspace: str, extraction_ref: dict
):
    if not request.use_expression_dictionary:
        return None
    from teoria.domains.goods.normalization.meaning_proposals.expression_alignment import (
        align_dictionary,
    )

    corpus = await load(Path(workspace) / "extracted.json")
    maintenance = None
    if request.mode == "standard_management" and corpus["documents"]:
        from teoria.domains.goods.normalization.meaning_proposals.expression_management import (
            collect_expression_proposals,
        )

        maintenance = await collect_expression_proposals(
            request, corpus, extraction_ref
        )
    return await align_dictionary(
        request, corpus, extraction_ref, maintenance=maintenance
    )


def attach_source_term_alignment(normalized, dictionary):
    if dictionary is not None:
        normalized["dictionary_meanings"] = dictionary.get("meaning_alignment", {})
        normalized["source_term_alignment"] = {
            "artifact": dictionary["alignment_ref"],
            "operation_id": dictionary["result"]["operation_id"],
            "summary": dictionary["summary"],
            "semantic_maturity": "source_literal",
            "human_review_performed": False,
            "meaning_summary": dictionary.get("meaning_summary", {}),
        }


@task(name="06b 게시 Ontology 참고·의미 연결 비교", **TASK_OPTIONS)
async def align_with_ontology(
    request: SpecificationRun, workspace: str, extraction_ref: dict, dictionary
):
    from teoria.domains.goods.authoring_client import GoodsAuthoringClient
    from teoria.domains.goods.normalization.meaning_proposals.ontology_context import (
        load_published_context,
    )
    from teoria.domains.goods.normalization.meaning_proposals.ontology_alignment import (
        propose_links,
    )

    corpus = await load(Path(workspace) / "extracted.json")
    async with GoodsAuthoringClient() as api:
        snapshot, catalog = await load_published_context(
            request.ontology_alignment, api, standard=request.standard
        )
    report = await propose_links(
        corpus,
        snapshot,
        catalog,
        (dictionary or {}).get("meaning_alignment"),
        runner(request),
        Path(workspace) / "ontology_alignment_inference",
    )
    context_input = request.ontology_alignment
    report.update(
        extraction_ref=extraction_ref,
        context_input_ref=(
            context_input.snapshot.model_dump(mode="json")
            if context_input.snapshot is not None
            else {
                "publications": [
                    ref.model_dump(mode="json") for ref in context_input.publications
                ]
            }
        ),
    )
    async with artifact_store(request.artifact_root) as store:
        context_ref = await store.put(
            run_key(request, "ontology_context.json"),
            snapshot.model_dump_json().encode(),
        )
        report["context_artifact"] = context_ref.model_dump(mode="json")
        report_ref = await store.put(
            run_key(request, "ontology_alignment.json"),
            (json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n").encode(),
        )
        candidates = {
            "schema_version": 1,
            "artifact_kind": "specification_ontology_context_review_candidates",
            "authority": "suggestion",
            "auto_approve": False,
            "reason": "selected_context_or_ontology_gap",
            "extraction_ref": extraction_ref,
            "context_artifact": context_ref.model_dump(mode="json"),
            "observations": [
                row
                for row in report["observations"]
                if row["ontology_review_candidate"]
            ],
        }
        unresolved_ref = await store.put(
            run_key(request, "ontology_alignment_unresolved.json"),
            (
                json.dumps(candidates, ensure_ascii=False, sort_keys=True) + "\n"
            ).encode(),
        )
    return {
        "report": report,
        "artifacts": [
            context_ref.model_dump(mode="json"),
            report_ref.model_dump(mode="json"),
            unresolved_ref.model_dump(mode="json"),
        ],
    }


@task(name="07 표준 의미 적용", **TASK_OPTIONS)
async def select_and_map_standard(
    request: SpecificationRun,
    workspace: str,
    extraction_ref: dict | None = None,
    dictionary=None,
    *,
    ontology_alignment=None,
):
    from teoria.domains.goods.normalization.application.extraction_rule_authoring import (
        manage_standard,
    )
    from teoria.domains.goods.normalization.application.extraction_rule_application import (
        map_standard,
    )
    from teoria.domains.goods.contracts import StandardReference

    corpus = await load(Path(workspace) / "extracted.json")
    standard = None
    if request.standard:
        raw = await read_uri(request.standard.uri)
        if hashlib.sha256(raw).hexdigest() != request.standard.sha256:
            raise ValueError("standard checksum mismatch")
        payload = json.loads(raw)
        if payload.get("artifact_kind") == "goods_normalization_package":
            from teoria.domains.goods.normalization.contracts import (
                NormalizationPackage,
            )
            from teoria.domains.goods.normalization.application.profile_application import (
                apply_profile,
            )

            package = NormalizationPackage.model_validate(payload)
            meaning_alignment = (
                dictionary.get("meaning_alignment") if dictionary else None
            )
            if (not request.use_expression_dictionary or meaning_alignment is None):
                # Disabling registration must not turn unreviewed aliases into approved meaning.
                meaning_alignment = {
                    "policy_version": "published_ontology_expression_v2",
                    "documents": [],
                }
            normalized, candidates = apply_profile(
                corpus,
                package,
                run_id=request.run_id,
                meaning_alignment=meaning_alignment,
            )
            if request.interpretation_revision_ids:
                from teoria.domains.goods.normalization.application.meaning_application import (
                    ApprovedInterpretation, apply_interpretation, merge_interpretations,
                )
                if len(set(request.interpretation_revision_ids)) != len(request.interpretation_revision_ids):
                    raise ValueError('duplicate_interpretation_revision')
                applications = []
                originals = {d['document_id']: d for d in corpus['documents']}
                async with GoodsAuthoringClient() as api:
                    publication = await api.ontology_publication(package.profile.ontology.version_id)
                    for revision_id in request.interpretation_revision_ids:
                        approval = ApprovedInterpretation.model_validate(await api.interpretation_approval(revision_id))
                        if approval.revision_id != revision_id:
                            raise ValueError('interpretation_revision_mismatch')
                        raw_result = await read_uri(approval.request.result.uri)
                        if hashlib.sha256(raw_result).hexdigest() != approval.request.result.sha256:
                            raise ValueError('interpretation_source_result_checksum_mismatch')
                        source_result = json.loads(raw_result); source_result = source_result.get('result',source_result)
                        original = originals.get(approval.request.document_id)
                        sources = source_result['extracted']['documents']
                        if (original is None or len(sources) != 1
                                or sources[0]['source']['sha256'] != original['source']['sha256']
                                or any(sources[0].get(k) != original.get(k) for k in
                                       ['document_id','entities','attributes','relations','parsed_document'])):
                            raise ValueError('interpretation_extraction_document_mismatch')
                        applications.append(apply_interpretation(approval, source_result, package, publication,
                                                                 run_id=request.run_id))
                normalized = merge_interpretations(normalized, applications, package)
                from teoria.domains.goods.normalization.application.profile_candidates import collect_profile_candidates
                candidates['bundle'] = collect_profile_candidates(corpus, normalized, package)
                candidates['candidates'] = normalized['unresolved_observations']
                candidates['summary'] = {'unresolved_observations': len(normalized['unresolved_observations'])}
                normalized['interpretation_revision_ids'] = [str(v) for v in request.interpretation_revision_ids]
            normalized["standard_ref"] = request.standard.model_dump()
            normalized["extraction_ref"] = extraction_ref
            attach_source_term_alignment(normalized, dictionary)
            if ontology_alignment is not None:
                normalized["ontology_alignment"] = ontology_alignment["report"]
            candidates["extraction_ref"] = extraction_ref
            artifacts = []
            async with artifact_store(request.artifact_root) as store:
                await save(Path(workspace) / "normalized.json", normalized)
                artifacts.append(
                    (
                        await store.put(
                            run_key(request, "normalized.json"),
                            await asyncio.to_thread(
                                (Path(workspace) / "normalized.json").read_bytes
                            ),
                        )
                    ).model_dump()
                )
                if request.mode == "standard_management":
                    await save(Path(workspace) / "meaning_candidates.json", candidates)
                    artifacts.append(
                        (
                            await store.put(
                                run_key(request, "meaning_candidates.json"),
                                (
                                    json.dumps(candidates, ensure_ascii=False, indent=2)
                                    + "\n"
                                ).encode(),
                            )
                        ).model_dump()
                    )
            return {"artifacts": artifacts, "standard": request.standard.model_dump()}
        standard = StandardArtifact.model_validate(payload)
    candidates = None
    if request.mode == "standard_management":
        standard, candidates, normalized = manage_standard(
            corpus,
            standard,
            request.standard.sha256 if request.standard else None,
            auto_apply_source_literals=request.auto_apply_source_literals,
        )
    else:
        normalized = map_standard(corpus, standard)
    artifacts = []
    async with artifact_store(request.artifact_root) as store:
        if request.mode == "standard_management":
            data = (standard.model_dump_json(indent=2) + "\n").encode()
            ref = await store.put(
                f"specification_processing/standards/{standard.version}/standard.json",
                data,
            )
            standard_ref = StandardReference(uri=ref.uri, sha256=ref.sha256)
            artifacts.append(ref.model_dump())
            ref = await store.put(
                run_key(request, "meaning_candidates.json"),
                (json.dumps(candidates, ensure_ascii=False, indent=2) + "\n").encode(),
            )
            artifacts.append(ref.model_dump())
        else:
            standard_ref = request.standard
        await save(
            Path(workspace) / "standard_definitions.json",
            [
                d.model_dump() if hasattr(d, "model_dump") else d
                for d in standard.definitions
            ],
        )
        normalized["standard_ref"] = standard_ref.model_dump()
        attach_source_term_alignment(normalized, dictionary)
        if ontology_alignment is not None:
            normalized["ontology_alignment"] = ontology_alignment["report"]
        await save(Path(workspace) / "normalized.json", normalized)
        ref = await store.put(
            run_key(request, "normalized.json"),
            await asyncio.to_thread((Path(workspace) / "normalized.json").read_bytes),
        )
        artifacts.append(ref.model_dump())
    if candidates is not None:
        await save(Path(workspace) / "meaning_candidates.json", candidates)
    return {"artifacts": artifacts, "standard": standard_ref.model_dump()}


@task(name="08 결과 보고서 저장", **TASK_OPTIONS)
async def persist_report(
    request: SpecificationRun, workspace: str, standard_version: str
):
    from teoria.domains.goods.normalization.reporting import render_report

    corpus = await load(Path(workspace) / "extracted.json")
    normalized = await load(Path(workspace) / "normalized.json")
    candidates = (
        await load(Path(workspace) / "meaning_candidates.json")
        if request.mode == "standard_management"
        else None
    )
    text = render_report(corpus, normalized, standard_version, candidates)
    async with artifact_store(request.artifact_root) as store:
        return (
            await store.put(
                run_key(request, "index.md"), text.encode(), "text/markdown"
            )
        ).model_dump()


@task(name="09 문서별 탐색 결과 저장", **TASK_OPTIONS)
async def persist_document_results(request: SpecificationRun, workspace: str):
    from teoria.domains.goods.data_processing.catalog.results import (
        store_document_results,
    )

    corpus = await load(Path(workspace) / "extracted.json")
    normalized = await load(Path(workspace) / "normalized.json")
    async with artifact_store(request.artifact_root) as store:
        definitions = (
            await load(Path(workspace) / "standard_definitions.json")
            if (Path(workspace) / "standard_definitions.json").exists()
            else []
        )
        return await store_document_results(
            store, request.run_id, corpus, normalized, definitions=definitions
        )


@task(name="00 추출 평가 근거 검증", **TASK_OPTIONS)
async def verify_quality_evaluation(request: SpecificationRun, revision: str):
    """Attach existing frozen-case evidence without certifying deployment or meaning."""
    if request.quality_evaluation is None:
        return None
    from teoria.domains.goods.data_processing.evaluation.release_quality import check_release_quality

    reference = request.quality_evaluation
    raw = await read_uri(reference.uri)
    if hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise ValueError("quality_evaluation_checksum_mismatch")
    cycle = json.loads(raw)
    from teoria.domains.goods.processor_revision import extraction_revision
    gate = check_release_quality(cycle, extraction_revision())
    if gate["status"] != "passed":
        raise ValueError("quality_evaluation_blocked:" + ",".join(gate["reasons"]))
    if not request.model or cycle["settings"]["model"] != request.model:
        raise ValueError("quality_evaluation_model_mismatch")
    async with artifact_store(request.artifact_root) as store:
        artifact = await store.put(run_key(request, "quality_evaluation.json"), raw)
    return {**gate, "source": reference.model_dump(mode="json"),
            "artifact": artifact.model_dump(mode="json"), "model": request.model}


@task(name="10 처리 버전·출처 기록 저장", **TASK_OPTIONS)
async def persist_execution_receipt(
    request: SpecificationRun, workspace: str, revision: str, references: list,
    quality_evaluation: dict | None = None,
):
    corpus = await load(Path(workspace) / "extracted.json")
    normalized = await load(Path(workspace) / "normalized.json")
    source_hashes = {
        d["document_id"]: d["source"]["sha256"]
        for d in [*corpus["documents"], *corpus["unavailable_documents"]]
    }
    receipt = {
        "schema_version": 2 if quality_evaluation else 1,
        "run_id": request.run_id,
        "mode": request.mode,
        "input_fingerprint": request.input_fingerprint(),
        "processor_revision": revision,
        "model": {"requested": request.model, "immutable_identity_verified": False},
        "parser_versions": sorted(
            {d["parser"]["version"] for d in corpus["documents"]}
        ),
        "sources": [
            {"document_id": d.document_id, "sha256": source_hashes[d.document_id]}
            for d in request.documents
        ],
        "application_release_id": str(request.application_release_id)
        if request.application_release_id
        else None,
        "standard": request.standard.model_dump(mode="json")
        if request.standard
        else None,
        "dictionary": request.dictionary_standard.model_dump(mode="json")
        if request.dictionary_standard
        else None,
        "ontology": normalized.get("ontology"),
        "ontology_alignment": request.ontology_alignment.model_dump(mode="json")
        if request.ontology_alignment
        else None,
        "artifacts": [
            {"key": a["key"], "uri": a["uri"], "sha256": a["sha256"]}
            for a in references
        ],
        "quality_evaluation": quality_evaluation or "not_attached",
    }
    async with artifact_store(request.artifact_root) as store:
        return (
            await store.put(
                run_key(request, "execution_receipt.json"),
                (
                    json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n"
                ).encode(),
            )
        ).model_dump()
