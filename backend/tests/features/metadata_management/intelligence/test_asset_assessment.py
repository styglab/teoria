from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from teoria.features.metadata_management.intelligence.asset_assessment.model_client import (
    AssessmentError,
    AssessmentModelClient,
)
from teoria.features.metadata_management.intelligence.asset_assessment.models import (
    AssessmentOutput,
    AssessmentRequest,
    LawQueries,
)
from teoria.features.metadata_management.intelligence.asset_assessment.service import (
    AssetAssessmentService,
)
from teoria.features.metadata_management.intelligence.asset_assessment.law_evidence import (
    law_search_queries,
)


def setup(scopes=None):
    identifier = str(uuid4())
    table = {
        "id": identifier,
        "name": "contracts",
        "version": 1.0,
        "fullyQualifiedName": "s.d.c.contracts",
        "columns": [
            {
                "name": "amount",
                "dataType": "DECIMAL",
                "fullyQualifiedName": "s.d.c.contracts.amount",
                "description": None,
            }
        ],
    }
    job = {
        "assessment_id": uuid4(),
        "claim_token": uuid4(),
        "model_name": "synthetic",
        "requested_by": "user:author",
        "scopes": scopes or ["metadata_enrichment"],
        "column_names": [],
        "assessment_date": "2026-10-15",
        "disclosure_context": "public_release",
        "target_ref": {
            "entity_id": identifier,
            "fully_qualified_name": table["fullyQualifiedName"],
            "version": 1.0,
        },
    }
    output = AssessmentOutput.model_validate(
        {
            "changes": [
                {
                    "kind": "description",
                    "column_name": "amount",
                    "description": "계약금액 후보",
                    "confidence": 0.95,
                    "reason": "메타데이터 대조",
                    "evidence_ids": ["column:amount"],
                }
            ]
        }
    )
    metadata = SimpleNamespace(get_table_by_name=AsyncMock(return_value=table))
    model = SimpleNamespace(model="synthetic", generate=AsyncMock(return_value=output))
    repo = Mock(finish=AsyncMock())
    service = AssetAssessmentService(repo, metadata, None, model)
    return service, job, table, output


@pytest.mark.asyncio
async def test_description_pending_payload_is_server_built_and_no_samples_are_used():
    service, job, table, output = setup()
    proposals, findings, partial = await service.analyze(job)
    assert not partial
    assert proposals[0]["proposed_value"] == {
        "table_id": table["id"],
        "column_name": "amount",
        "column_fqn": "s.d.c.contracts.amount",
        "source_version": "1.0",
        "source_description": None,
        "description": "계약금액 후보",
    }
    assert proposals[0]["submitted_by"] == "user:author"
    assert proposals[0]["confidence"] == 0.69
    assert (
        "source_description" not in service.model.generate.call_args.kwargs["context"]
    )
    assert "rows" not in str(service.model.generate.call_args.kwargs["context"])


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["column", "citation", "scope"])
async def test_invalid_model_target_citation_or_scope_is_not_submitted(mutation):
    service, job, table, output = setup()
    if mutation == "column":
        output.changes[0].column_name = "invented_column"
    elif mutation == "citation":
        output.changes[0].evidence_ids = ["invented_law"]
    else:
        job["scopes"] = ["semantic_alignment"]
        service.bindings = Mock(
            list_published_property_concepts=AsyncMock(return_value=[])
        )
    proposals, findings, partial = await service.analyze(job)
    assert proposals == [] and partial
    assert findings[-1]["code"] == "invalid_candidates_excluded"


@pytest.mark.asyncio
async def test_asset_change_during_model_call_discards_all_results():
    service, job, table, _ = setup()
    service.metadata.get_table_by_name.side_effect = [table, {**table, "version": 1.1}]
    with pytest.raises(AssessmentError, match="stale_evidence"):
        await service.analyze(job)


@pytest.mark.asyncio
async def test_failure_does_not_persist_exception_payloads():
    service, job, _, _ = setup()
    service.model.generate.side_effect = RuntimeError("sensitive provider payload")
    await service.process(job)
    service.repository.finish.assert_called_once_with(
        job, proposals=[], findings=[], error_code="assessment_failed"
    )


@pytest.mark.asyncio
async def test_lawless_disclosure_is_not_a_positive_legal_conclusion():
    service, job, _, _ = setup(["disclosure_assessment"])
    service.model.generate.return_value = AssessmentOutput.model_validate(
        {
            "findings": [
                {
                    "scope": "disclosure_assessment",
                    "summary": "개방 가능 추정",
                    "internal_processing": "basis_identified",
                    "disclosure_recommendation": "candidate",
                    "tag_candidates": ["Disclosure.Open"],
                    "evidence_ids": ["column:amount"],
                }
            ]
        }
    )
    proposals, findings, partial = await service.analyze(job)
    finding = next(item for item in findings if "legal_applicability_confirmed" in item)
    assert partial and not proposals
    assert finding["legal_applicability_confirmed"] is False
    assert finding["disclosure_recommendation"] == "review_required"
    assert finding["internal_processing"] == "review_required"
    assert finding["tag_candidates"] == []


@pytest.mark.asyncio
async def test_legal_findings_keep_verified_snapshot_provenance_and_do_not_become_tags():
    service, job, _, _ = setup(["disclosure_assessment"])
    snapshot_id = uuid4()
    key = "law:1"
    hit = {
        "snapshot_id": snapshot_id,
        "path": "article/1",
        "law_id": "1",
        "mst": "10",
        "law_name": "Synthetic Law",
        "effective_date": "2020-01-01",
    }
    service.law_reader = Mock(
        search=AsyncMock(return_value={"items": [hit], "unavailable_versions": []}),
        get_document=AsyncMock(
            return_value={
                **hit,
                "content": "Synthetic provision",
                "content_truncated": False,
            }
        ),
    )
    service.model.generate.side_effect = [
        LawQueries(queries=["식별정보"]),
        AssessmentOutput.model_validate(
            {
                "findings": [
                    {
                        "scope": "disclosure_assessment",
                        "summary": "처리 근거 검토",
                        "evidence_ids": [key],
                    }
                ]
            }
        ),
    ]
    proposals, findings, partial = await service.analyze(job)
    assert not proposals and not partial
    assert findings[0]["evidence"][0]["provenance"]["snapshot_id"] == str(snapshot_id)
    assert findings[0]["legal_applicability_confirmed"] is False


@pytest.mark.asyncio
async def test_existing_binding_is_not_proposed_again():
    service, job, table, _ = setup(["semantic_alignment"])
    identifier = str(uuid4())
    concept = {
        "concept_id": identifier,
        "concept_kind": "property",
        "stable_key": "test.contract.amount",
        "name": "Amount",
        "code": "amount",
        "value_type": "decimal",
        "version": "1.0",
    }
    service.bindings = Mock(
        list_published_property_concepts=AsyncMock(return_value=[concept]),
        get_active_binding=AsyncMock(return_value={"status": "approved"}),
    )
    service.model.generate.return_value = AssessmentOutput.model_validate(
        {
            "changes": [
                {
                    "kind": "binding",
                    "column_name": "amount",
                    "concept_id": identifier,
                    "confidence": 0.8,
                    "reason": "existing concept",
                    "evidence_ids": ["column:amount", f"concept:{identifier}"],
                }
            ]
        }
    )
    proposals, _, partial = await service.analyze(job)
    assert not proposals and not partial
    service.bindings.get_active_binding.assert_called_once()


@pytest.mark.asyncio
async def test_model_omitting_disclosure_cannot_report_completed_legal_assessment():
    service, job, _, _ = setup(["disclosure_assessment"])
    service.model.generate.return_value = AssessmentOutput()
    _, findings, partial = await service.analyze(job)
    assert partial
    assert any(item.get("code") == "disclosure_result_missing" for item in findings)


def test_request_rejects_actor_samples_and_new_ontology_scope():
    for extra in (
        {"actor": "forged"},
        {"use_samples": True},
        {"scopes": ["ontology_change"]},
    ):
        with pytest.raises(ValueError):
            AssessmentRequest.model_validate(
                {"table_fqn": "s.d.c.t", "scopes": ["metadata_enrichment"], **extra}
            )


def test_korean_law_lookup_does_not_depend_on_model_translating_english_columns():
    queries = law_search_queries(
        [{"name": "representative_name"}], ["representative privacy"]
    )
    assert queries == ["개인정보", "공공데이터"]
    assert (
        len(
            law_search_queries(
                [{"name": "rrn_name_health"}], ["개인정보 처리", "민감정보"]
            )
        )
        <= 3
    )


@pytest.mark.asyncio
async def test_codex_uses_typed_schema_and_discards_temporary_output():
    paths = []

    async def generate(instruction, context, output, *, output_schema):
        assert "synthetic instruction" in instruction
        assert context == {"source": "synthetic"}
        assert "changes" in output_schema["properties"]
        assert "findings" in output_schema["properties"]
        assert output.parent.exists()
        paths.append(output)
        output.write_text("synthetic temporary output")
        return {"changes": [], "findings": []}

    runner = SimpleNamespace(generate=generate)
    model = AssessmentModelClient(model="synthetic", runner=runner)
    result = await model.generate(instruction="synthetic instruction", context={"source": "synthetic"}, output_type=AssessmentOutput)
    assert result == AssessmentOutput()
    assert model.model == "codex:synthetic"
    assert not paths[0].parent.exists()


@pytest.mark.parametrize("failure,code", [
    (TimeoutError("private provider text"), "model_timeout"),
    (RuntimeError("private provider text"), "model_unavailable"),
    (ValueError("private incomplete JSON"), "model_output_invalid"),
])
async def test_codex_failures_expose_only_stable_codes_and_do_not_fallback(failure, code):
    runner = SimpleNamespace(generate=AsyncMock(side_effect=failure))
    model = AssessmentModelClient(runner=runner)
    with pytest.raises(AssessmentError, match=code) as error:
        await model.generate(instruction="test", context={}, output_type=AssessmentOutput)
    assert "private" not in str(error.value)
    runner.generate.assert_awaited_once()


async def test_codex_rejects_invalid_schema_and_oversized_output():
    for output, code in [({"unknown": True}, "model_output_invalid"), ({"large": "x" * 200001}, "model_response_too_large")]:
        model = AssessmentModelClient(runner=SimpleNamespace(generate=AsyncMock(return_value=output)))
        with pytest.raises(AssessmentError, match=code):
            await model.generate(instruction="test", context={}, output_type=AssessmentOutput)


async def test_codex_cancellation_propagates_and_removes_temporary_files():
    import asyncio
    paths = []
    async def generate(instruction, context, output, **kwargs):
        paths.append(output)
        output.write_text("synthetic")
        raise asyncio.CancelledError
    model = AssessmentModelClient(runner=SimpleNamespace(generate=generate))
    with pytest.raises(asyncio.CancelledError):
        await model.generate(instruction="test", context={}, output_type=AssessmentOutput)
    assert not paths[0].parent.exists()


@pytest.mark.asyncio
async def test_law_context_budget_limits_documents_without_dropping_provenance():
    from teoria.features.metadata_management.intelligence.asset_assessment.law_evidence import collect_law_evidence
    identifiers = [uuid4(), uuid4()]
    hits = [{"snapshot_id": item, "path": "article/1", "law_id": str(index+1),
        "mst": "10", "law_name": "Synthetic Law", "effective_date": "2020-01-01"}
        for index,item in enumerate(identifiers)]
    reader = Mock(search=AsyncMock(return_value={"items": hits, "unavailable_versions": []}),
        get_document=AsyncMock(return_value={**hits[0], "content": "Synthetic provision", "content_truncated": False}))
    model = Mock(generate=AsyncMock(return_value=LawQueries(queries=["개인정보"])))
    context, evidence = {}, {}
    await collect_law_evidence({"scopes": ["disclosure_assessment"], "assessment_date": "2026-10-27"},
        [{"name": "email"}], context, evidence, model, reader, max_documents=1, max_chars=1000)
    assert len(context["law_documents"]) == 1
    assert reader.get_document.await_count == 1
    assert reader.get_document.call_args.kwargs["max_chars"] == 1000
    assert evidence["law:1"]["provenance"]["snapshot_id"] == str(identifiers[0])
