from inspect import Parameter, signature
import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import yaml
import pytest

from teoria_pipelines.flows.pps_contracts import (
    sync_pps_contract_backfill,
    sync_pps_contract_incremental,
    sync_pps_contract_window,
    sync_pps_contracts,
)
from teoria_pipelines.tasks.pps_contracts import extract_contract_operation
from teoria_pipelines.flows.pps_bid_notices import (
    purge_expired_pps_bid_documents,
    sync_pps_bid_documents,
    sync_pps_bid_notices,
)
from teoria_pipelines.tasks.bid_eligibility import _ensure_codex_authenticated
from teoria_pipelines.flows.bid_eligibility import _extraction_summary, extract_pps_bid_eligibility
from teoria_pipelines.tasks.bid_eligibility import (
    _citation_text,
    _citation_similarity,
    _consolidate_requirements,
    _ellipsis_fragments_match,
    _reconcile_document_citations,
    _reconcile_original_text,
    _repair_requirement_fields,
    _skill_instructions,
    _prioritize_notices,
    _structured_api_result,
    _validate_citations,
    _validate_semantic_normalization,
    extract_bid_eligibility_notice,
    normalize_structured_bid_eligibility_notice,
)
from teoria_pipelines.persistence.postgres import _sanitize_postgres_value, eligibility_requires_review


PIPELINES = Path(__file__).parents[2]
from teoria_pipelines.tasks.pps_contracts import (
    complete_pipeline_run,
    combine_extracted_batches,
    determine_collection_window,
    extract_contract_operation,
    normalize_contracts,
    save_raw_records,
    update_checkpoint,
    upsert_contracts,
)


def test_prefect_flow_and_task_names_are_operationally_readable() -> None:
    assert sync_pps_contracts.name == "나라장터 계약정보 수집"
    assert sync_pps_contract_incremental.name == "나라장터 계약정보 증분 수집"
    assert sync_pps_contract_backfill.name == "나라장터 계약정보 Backfill"
    assert sync_pps_contract_window.name == "나라장터 계약정보 일별 수집"
    assert [
        determine_collection_window.name,
        extract_contract_operation.name,
        combine_extracted_batches.name,
        save_raw_records.name,
        normalize_contracts.name,
        upsert_contracts.name,
        update_checkpoint.name,
        complete_pipeline_run.name,
    ] == [
        "수집 구간 결정",
        "나라장터 Operation 수집",
        "Operation 응답 결합",
        "Raw 응답 저장",
        "계약정보 정규화",
        "정규 테이블 Upsert",
        "Checkpoint 갱신",
        "수집 실행 완료",
    ]


def test_daily_flow_mermaid_graph_exposes_execution_order() -> None:
    graph = sync_pps_contract_window.generate_mermaid_graph(
        window=CollectionWindow(date(2026, 7, 1), date(2026, 7, 1)),
        pipeline_root="pipelines",
    )

    assert "수집_실행_시작_0 --> 상품_계약_API_수집_0" in graph
    assert "상품_계약_API_수집_0 --> 공사_계약_API_수집_0" in graph
    assert "외자_계약_API_수집_0 --> Operation_응답_결합_0" in graph
    assert "Operation_응답_결합_0 --> Raw_응답_저장_0" in graph
    assert "Raw_응답_저장_0 --> 계약정보_정규화_0" in graph
    assert "정규_테이블_Upsert_0 --> Checkpoint_갱신_0" in graph
    assert "Checkpoint_갱신_0 --> 수집_실행_완료_0" in graph


def test_backfill_deployment_has_a_fixed_historical_range() -> None:
    prefect = yaml.safe_load((PIPELINES / "prefect.yaml").read_text(encoding="utf-8"))
    deployment = next(
        item for item in prefect["deployments"] if item["name"] == "pps-contract-backfill"
    )

    assert deployment["parameters"] == {
        "checkpoint_id": "pps_contract_backfill_2020_2025",
        "start_date": "2020-01-01",
        "end_date": "2025-12-31",
        "pipeline_root": "/app/pipelines",
        "batch_days": 30,
    }
    assert deployment["concurrency_limit"] == {
        "limit": 1,
        "collision_strategy": "CANCEL_NEW",
    }

    parameters = signature(sync_pps_contract_backfill.fn).parameters
    assert all(
        parameters[name].default is Parameter.empty
        for name in ("checkpoint_id", "start_date", "end_date")
    )


def test_incremental_deployment_prevents_overlapping_runs() -> None:
    prefect = yaml.safe_load((PIPELINES / "prefect.yaml").read_text(encoding="utf-8"))
    deployment = next(
        item for item in prefect["deployments"] if item["name"] == "pps-contract-incremental"
    )

    assert deployment["concurrency_limit"] == {
        "limit": 1,
        "collision_strategy": "CANCEL_NEW",
    }


def test_operation_task_retries_once_after_five_minutes() -> None:
    assert extract_contract_operation.retries == 1
    assert extract_contract_operation.retry_delay_seconds == 300


def test_codex_authentication_uses_cached_chatgpt_login() -> None:
    with patch(
        "teoria_pipelines.tasks.bid_eligibility.subprocess.run",
        return_value=CompletedProcess(["codex", "login", "status"], 0),
    ) as run:
        _ensure_codex_authenticated()

    assert run.call_args.args[0] == ["codex", "login", "status"]


def test_codex_authentication_failure_has_login_instruction() -> None:
    with patch(
        "teoria_pipelines.tasks.bid_eligibility.subprocess.run",
        return_value=CompletedProcess(["codex", "login", "status"], 1),
    ):
        try:
            _ensure_codex_authenticated()
        except RuntimeError as exc:
            assert "codex login --device-auth" in str(exc)
        else:
            raise AssertionError("missing Codex login must fail")


def test_bid_eligibility_extraction_runs_independent_notices_two_at_a_time() -> None:
    assert extract_pps_bid_eligibility.task_runner._max_workers == 2
    assert extract_bid_eligibility_notice.name == "공고별 Codex 참가자격 추출"
    assert extract_bid_eligibility_notice.retries == 2
    assert extract_bid_eligibility_notice.retry_delay_seconds == 120
    assert normalize_structured_bid_eligibility_notice.name == "공고별 API 참가자격 정규화"


def test_structured_api_eligibility_preserves_license_groups_and_region_alternatives() -> None:
    result = _structured_api_result({
        "licenses": [
            {"group": "1", "sequence": "1", "name": "전기공사업/0037",
             "permitted_industries": None, "main_fields": None, "business_type": "공사"},
            {"group": "1", "sequence": "2", "name": "정보통신공사업/0036",
             "permitted_industries": None, "main_fields": None, "business_type": "공사"},
        ],
        "regions": [
            {"sequence": "1", "name": "서울특별시", "business_type": "공사"},
            {"sequence": "2", "name": "경기도", "business_type": "공사"},
        ],
    })
    assert [item["type"] for item in result["requirements"]] == [
        "industry_license", "industry_license", "participation_region", "participation_region"
    ]
    assert result["expression"]["operator"] == "all"
    assert [branch["operator"] for branch in result["expression"]["conditions"]] == ["any", "any"]
    assert all(item["evidence"][0]["source_type"] == "structured_api"
               for item in result["requirements"])


def test_eligibility_batch_reserves_capacity_for_documents_and_api_only() -> None:
    document_notices = [{"notice_number": f"doc-{index}", "notice_order": "0", "documents": [{}]}
                        for index in range(12)]
    api_notices = [{"notice_number": f"api-{index}", "notice_order": "0", "documents": []}
                   for index in range(5)]
    selected = _prioritize_notices(document_notices + api_notices, 10)
    assert sum(bool(item["documents"]) for item in selected) == 8
    assert sum(not item["documents"] for item in selected) == 2


def test_document_citation_comparison_normalizes_unicode_and_whitespace() -> None:
    assert _citation_text("중소기업\n 확인서") == _citation_text("중소기업   확인서")
    assert _citation_text("ＡＢＣ") == "ABC"


def test_document_citation_is_reassigned_to_the_actual_duplicate_block() -> None:
    inputs = {
        "structured_requirements": [],
        "documents": [
            {"document_id": "doc-wrong", "content": {"blocks": [
                {"block_id": "b1", "page": 1, "section": None, "text": "일반 안내"}
            ]}},
            {"document_id": "doc-right", "content": {"blocks": [
                {"block_id": "b7", "page": 2, "section": "참가자격",
                 "text": "전기공사업 등록을 필한 업체이어야 합니다."}
            ]}},
        ],
    }
    evidence = {"source_type": "document", "source_id": "doc-wrong",
                "document_id": "doc-wrong", "block_id": "b1", "page": 1,
                "section": None, "excerpt": "전기공사업 등록을 필한 업체이어야 합니다."}
    result = {"requirements": [{"evidence": [evidence]}]}
    _reconcile_document_citations(result, inputs)
    assert evidence["document_id"] == "doc-right"
    assert evidence["block_id"] == "b7"
    assert evidence["page"] == 2


def test_ellipsis_fragments_require_ordered_verbatim_source_text() -> None:
    source = "입찰공고일로부터 1년 이내인 경우에는 해당 확약서를 제출하여야 합니다."

    assert _ellipsis_fragments_match(
        "입찰공고일로부터 1년 이내인 경우에는...해당 확약서를 제출하여야 합니다.",
        source,
    )
    assert not _ellipsis_fragments_match(
        "해당 확약서를 제출하여야 합니다...입찰공고일로부터 1년 이내인 경우에는",
        source,
    )


def test_citation_similarity_accepts_legal_parenthetical_omission() -> None:
    source = (
        "당해 시설물을 설계·시공·감리한 자 또는 그 계열회사"
        "(독점규제 및 공정거래에 관한 법률에 따른 계열회사)인 기관은 참여할 수 없습니다."
    )
    paraphrased = "당해 시설물을 설계·시공·감리한 자 또는 그 계열회사인 기관은 참여할 수 없습니다."

    assert _citation_similarity(paraphrased, source) >= 0.58


def test_citation_similarity_accepts_spaces_inside_korean_words() -> None:
    source = "중 소기 업 ㆍ 소 상 공인 확 인 서 가 공공 구 매 종 합정 보 망 에 서 확 인 되어야 함"
    excerpt = "중소기업ㆍ소상공인 확인서가 공공구매 종합정보망에서 확인되어야 함"

    assert _citation_similarity(excerpt, source) >= 0.58


def test_reconcile_uses_unique_ocr_spaced_block() -> None:
    inputs = {"structured_requirements": [], "documents": [{
        "document_id": "pdf", "content": {"blocks": [
            {"block_id": "p3~1", "page": 3, "section": None, "text": "일반 입찰 안내"},
            {"block_id": "p3~3", "page": 3, "section": "참가자격",
             "text": "중 소기 업 ㆍ 소 상 공인 확 인 서 가 공공 구 매 종 합정 보 망 에 서 확 인 되어야 함"},
        ]},
    }]}
    evidence = {"source_type": "document", "source_id": "pdf", "document_id": "pdf",
                "block_id": "p3", "page": 3, "section": None,
                "excerpt": "중소기업ㆍ소상공인 확인서가 공공구매 종합정보망에서 확인되어야 함"}
    result = {"requirements": [{"evidence": [evidence]}]}

    _reconcile_document_citations(result, inputs)

    assert evidence["block_id"] == "p3~3"
    assert evidence["excerpt"] == inputs["documents"][0]["content"]["blocks"][1]["text"]


def test_consolidates_document_and_structured_requirement_and_rewrites_expression() -> None:
    document_evidence = {"source_type": "document", "source_id": "doc", "document_id": "doc",
                         "block_id": "b1", "page": 1, "section": None, "excerpt": "업종 1253"}
    structured_evidence = {"source_type": "structured_api", "source_id": "license:1:1",
                           "document_id": None, "block_id": None, "page": None,
                           "section": None, "excerpt": "중간처리업/1253"}
    base = {"type": "industry_license", "operator": "exists", "holder_scope": "bidder",
            "reference_date_type": "none", "mandatory": True, "review_status": "extracted",
            "confidence": 1.0}
    result = {
        "requirements": [
            {**base, "id": "r1", "value": {"text": "중간처리업", "number": None,
             "boolean": True, "items": ["1253"], "attributes": []},
             "original_text": "업종 1253", "evidence": [document_evidence, document_evidence]},
            {**base, "id": "r2", "value": {"text": "중간처리업", "number": None,
             "boolean": True, "items": ["1253"], "attributes": [
                 {"name": "industry_code", "value": "1253"}]},
             "original_text": "중간처리업/1253", "evidence": [structured_evidence]},
        ],
        "expression": {"operator": "all", "requirement_id": None, "conditions": [
            {"operator": "leaf", "requirement_id": "r1", "conditions": []},
            {"operator": "leaf", "requirement_id": "r2", "conditions": []},
        ]},
    }

    _consolidate_requirements(result)

    assert [item["id"] for item in result["requirements"]] == ["r1"]
    assert {item["source_type"] for item in result["requirements"][0]["evidence"]} == {
        "document", "structured_api"
    }
    assert len(result["requirements"][0]["evidence"]) == 2
    assert result["expression"] == {"operator": "leaf", "requirement_id": "r1", "conditions": []}


def test_extraction_review_rolls_up_requirement_and_unresolved_state() -> None:
    notice = {"coverage": {"requires_review": False}}
    result = {"requirements": [{"review_status": "extracted"}], "unresolved_candidates": []}
    assert not eligibility_requires_review(notice, result)

    result["requirements"][0]["review_status"] = "needs_review"
    assert eligibility_requires_review(notice, result)
    result["requirements"][0]["review_status"] = "extracted"
    result["unresolved_candidates"] = [{
        "text": "추가 확인", "review_reason": "referenced_document_missing",
        "blocks_qualification": True,
    }]
    assert eligibility_requires_review(notice, result)
    result["unresolved_candidates"][0]["blocks_qualification"] = False
    assert not eligibility_requires_review(notice, result)
    result["unresolved_candidates"] = []
    result["requirements"][0]["failure_effect"] = "needs_review"
    assert eligibility_requires_review(notice, result)
    result["requirements"][0]["failure_effect"] = "cannot_bid"
    result["requirements"][0]["proof_requirements"] = [{"review_status": "needs_review"}]
    assert eligibility_requires_review(notice, result)


def test_extraction_skill_separates_eligibility_stages_and_proofs() -> None:
    skill_root = PIPELINES.parent / ".agents/skills/extract-bid-eligibility"
    with patch("teoria_pipelines.tasks.bid_eligibility.SKILL_ROOT", skill_root):
        policy = _skill_instructions()

    assert "bid entry, qualification review, or contracting" in policy
    assert "offered-product specifications and conformity" in policy
    assert "vehicle allocation" in policy
    assert "submission checklist" in policy
    assert "requested proof" in policy
    assert "unresolved_candidates" in policy
    assert "semantic normalization pass" in policy
    assert "never keep both a known-type requirement and a `custom`" in policy
    assert "`공동수급 불허` and `하도급 불허`" in policy
    assert "electronic certificate registration" in policy
    assert "`consortium_representative`" in policy
    assert "직접생산확인증명서 as `certificate`" in policy
    assert "never by source text alone" in policy
    assert "logic.placements" in policy
    assert "Pipeline, not the model" in policy
    assert "proof_requirements" in policy
    assert "qualification_review" in policy
    assert "failure_effect" in policy
    assert "조세포탈" in policy


def test_extraction_schema_distinguishes_consortium_representative_scope() -> None:
    schema_path = (PIPELINES.parent / ".agents/skills/extract-bid-eligibility/references/"
                   "eligibility-extraction.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    scopes = schema["properties"]["requirements"]["items"]["properties"]["holder_scope"]["enum"]

    assert "representative" in scopes
    assert "consortium_representative" in scopes


def test_semantic_normalization_rejects_custom_duplicate_of_known_type() -> None:
    evidence = [{"source_type": "document", "source_id": "doc", "document_id": "doc",
                 "block_id": "b1", "page": 1, "section": None, "excerpt": "공동도급 불허"}]
    base = {"operator": "exists", "value": {"text": "공동도급 불허", "number": None,
            "boolean": None, "items": [], "attributes": []}, "original_text": "공동도급 불허",
            "holder_scope": "bidder", "reference_date_type": "bid_deadline", "mandatory": True,
            "review_status": "extracted", "confidence": 1.0, "evidence": evidence}
    result = {"requirements": [
        {**base, "id": "r1", "type": "consortium"},
        {**base, "id": "r2", "type": "custom"},
    ]}

    with pytest.raises(ValueError, match="custom_duplicates_known_requirement"):
        _validate_semantic_normalization(result)


def test_semantic_normalization_rejects_duplicate_proposition_with_same_type() -> None:
    evidence = [{"source_type": "document", "source_id": "doc", "document_id": "doc",
                 "block_id": "b1", "page": 1, "section": None, "excerpt": "공동도급 불허"}]
    base = {"type": "consortium", "operator": "exists",
            "value": {"text": "공동도급 불허", "number": None, "boolean": None,
                      "items": [], "attributes": []}, "original_text": "공동도급 불허",
            "holder_scope": "bidder", "reference_date_type": "bid_deadline", "mandatory": True,
            "review_status": "extracted", "confidence": 1.0, "evidence": evidence}
    result = {"requirements": [{**base, "id": "r1"}, {**base, "id": "r2"}]}

    with pytest.raises(ValueError, match="duplicate_requirement_proposition"):
        _validate_semantic_normalization(result)


def test_semantic_normalization_rejects_joined_joint_and_subcontract_facts() -> None:
    result = {"requirements": [{
        "id": "r1", "type": "consortium", "operator": "not_exists",
        "value": {"text": "공동수급 및 하도급 불허", "number": None, "boolean": False,
                  "items": [], "attributes": []},
        "original_text": "공동수급 및 하도급 불허", "holder_scope": "bidder",
        "reference_date_type": "bid_deadline", "mandatory": True,
        "review_status": "extracted", "confidence": 1.0,
        "evidence": [{"source_type": "document", "source_id": "doc", "document_id": "doc",
                      "block_id": "b1", "page": 1, "section": None,
                      "excerpt": "공동수급 및 하도급 불허"}],
    }]}

    with pytest.raises(ValueError, match="non_atomic_consortium_requirement"):
        _validate_semantic_normalization(result)


def test_semantic_normalization_rejects_same_semantic_value_despite_different_source_text() -> None:
    evidence = [{"source_type": "document", "source_id": "doc", "document_id": "doc",
                 "block_id": "b1", "page": 1, "section": None,
                 "excerpt": "나라장터 업체 및 전자입찰용 인증서 등록을 마감 전까지 완료해야 합니다."}]
    base = {"type": "procurement_registration", "operator": "exists",
            "value": {"text": "등록", "number": None, "boolean": True,
                      "items": [], "attributes": []}, "holder_scope": "bidder",
            "reference_date_type": "bid_deadline", "mandatory": True,
            "review_status": "extracted", "confidence": 1.0, "evidence": evidence}
    result = {"requirements": [
        {**base, "id": "r1", "original_text": "나라장터 입찰자 등록 및 업체 전자입찰용 인증서 등록을 마감 전까지 완료해야 합니다."},
        {**base, "id": "r2", "original_text": "업체 전자입찰용 인증서 등록을 마감 전까지 완료해야 합니다."},
    ]}

    with pytest.raises(ValueError, match="duplicate_requirement_proposition"):
        _validate_semantic_normalization(result)


def test_semantic_normalization_allows_atomic_facts_from_same_compound_source() -> None:
    evidence = [{"source_type": "document", "source_id": "doc", "document_id": "doc",
                 "block_id": "b1", "page": 1, "section": None,
                 "excerpt": "공동도급 및 하도급을 허용하지 않습니다."}]
    base = {"type": "consortium", "operator": "not_exists",
            "value": {"text": None, "number": None, "boolean": False,
                      "items": [], "attributes": []},
            "original_text": "공동도급 및 하도급을 허용하지 않습니다.",
            "reference_date_type": "bid_deadline", "mandatory": True,
            "review_status": "extracted", "confidence": 1.0, "evidence": evidence}
    result = {"requirements": [
        {**base, "id": "r1", "holder_scope": "bidder",
         "value": {**base["value"], "text": "공동도급 불허"}},
        {**base, "id": "r2", "holder_scope": "subcontractor",
         "value": {**base["value"], "text": "하도급 불허"}},
    ]}

    _validate_semantic_normalization(result)


def test_semantic_normalization_requires_tax_evasion_as_sanction() -> None:
    result = {"requirements": [{
        "id": "r1", "type": "legal_qualification", "operator": "not_exists",
        "value": {"text": "조세포탈 유죄 확정 후 2년 미경과", "number": 2,
                  "boolean": False, "items": [], "attributes": []},
        "original_text": "조세포탈 등을 한 자로서 유죄판결 확정 후 2년이 지나지 않은 자",
        "holder_scope": "bidder", "reference_date_type": "bid_deadline",
        "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
        "comparison_mode": "structured", "proof_requirements": [],
        "mandatory": True, "review_status": "extracted", "confidence": 1.0,
        "evidence": [],
    }]}

    with pytest.raises(ValueError, match="tax_evasion_must_be_sanction"):
        _validate_semantic_normalization(result)


def test_semantic_normalization_rejects_qualification_review_as_bid_entry() -> None:
    result = {"requirements": [{
        "id": "r1", "type": "equipment_ownership", "operator": "exists",
        "value": {"text": "수집·운반 장비", "number": None, "boolean": True,
                  "items": [], "attributes": []},
        "original_text": "적격심사 시 장비보유현황증명서를 제출하여야 합니다.",
        "proposition_text": "적격심사 시 장비보유현황증명서를 제출하여야 합니다.",
        "holder_scope": "bidder", "reference_date_type": "bid_deadline",
        "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
        "comparison_mode": "document_evidence", "proof_requirements": [],
        "mandatory": True, "review_status": "extracted", "confidence": 1.0,
        "evidence": [],
    }]}

    with pytest.raises(ValueError, match="qualification_review_stage_mismatch"):
        _validate_semantic_normalization(result)


def test_consolidation_preserves_distinct_reference_dates_and_comparison_modes() -> None:
    base = {
        "type": "participation_region", "operator": "equals", "holder_scope": "bidder",
        "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
        "value": {"text": "경기도", "number": None, "boolean": None,
                  "items": [], "attributes": []},
        "original_text": "경기도 소재 업체", "mandatory": True,
        "review_status": "extracted", "confidence": 1.0, "evidence": [],
        "proof_requirements": [],
    }
    result = {"requirements": [
        {**base, "id": "r1", "reference_date_type": "notice_date",
         "comparison_mode": "structured"},
        {**base, "id": "r2", "reference_date_type": "bid_deadline",
         "comparison_mode": "manual"},
    ]}

    _consolidate_requirements(result)

    assert [item["id"] for item in result["requirements"]] == ["r1", "r2"]


def _validated_requirement(original_text: str, **overrides: object) -> dict:
    item = {
        "id": "r1", "type": "legal_qualification", "operator": "exists",
        "value": {"text": original_text, "number": None, "boolean": True,
                  "items": [], "attributes": []},
        "original_text": original_text, "holder_scope": "bidder",
        "reference_date_type": "bid_deadline", "assessment_stage": "bid_entry",
        "failure_effect": "cannot_bid", "comparison_mode": "manual",
        "proof_requirements": [], "mandatory": True, "review_status": "extracted",
        "confidence": 1.0,
        "evidence": [{"source_type": "document", "source_id": "doc",
                      "document_id": "doc", "block_id": "b1", "page": 1,
                      "section": None, "excerpt": original_text}],
    }
    item.update(overrides)
    return item


def test_semantic_normalization_requires_verbatim_original_text() -> None:
    item = _validated_requirement("입찰 참가자격을 갖춘 자")
    item["original_text"] = "입찰 참가자격 보유 업체"

    with pytest.raises(ValueError, match="original_text_must_be_verbatim_evidence"):
        _validate_semantic_normalization({"requirements": [item]})


def test_semantic_normalization_rejects_bid_price_formula() -> None:
    item = _validated_requirement("예정가격 대비 견적가격이 89.745% 이상인 자")

    with pytest.raises(ValueError, match="bid_price_must_not_be_eligibility"):
        _validate_semantic_normalization({"requirements": [item]})


def test_semantic_normalization_ignores_incidental_price_in_shared_evidence() -> None:
    item = _validated_requirement(
        "전자수의, 총액입찰, 단독이행, 제한적 최저가(낙찰하한율 89.745%)",
        type="consortium",
        value={"text": "단독이행", "number": None, "boolean": True,
               "items": [], "attributes": []},
    )

    _validate_semantic_normalization({"requirements": [item]})


def test_semantic_normalization_rejects_bid_registration_as_contracting() -> None:
    item = _validated_requirement(
        "정보통신공사업으로 입찰참가 등록한 자",
        assessment_stage="contracting", failure_effect="cannot_contract",
    )

    with pytest.raises(ValueError, match="bid_entry_registration_must_not_be_contracting"):
        _validate_semantic_normalization({"requirements": [item]})


def test_contracting_sanction_may_reference_bid_participation_restriction() -> None:
    item = _validated_requirement(
        "계약 위반 시 입찰참가자격 제한 처분을 받습니다.",
        type="sanction", operator="not_exists", assessment_stage="contracting",
        failure_effect="cannot_contract",
    )

    _validate_semantic_normalization({"requirements": [item]})


def test_semantic_normalization_rejects_implicit_bid_deadline_for_review() -> None:
    item = _validated_requirement(
        "적격심사 시 장비보유현황을 확인합니다.",
        assessment_stage="qualification_review",
        failure_effect="qualification_rejection",
        reference_date_type="bid_deadline",
    )

    with pytest.raises(ValueError, match="qualification_review_bid_deadline_not_explicit"):
        _validate_semantic_normalization({"requirements": [item]})


def test_semantic_normalization_accepts_explicit_quotation_deadline_for_review() -> None:
    item = _validated_requirement(
        "견적서 제출 마감일 현재 부도·파산·해산·영업정지가 확정된 경우",
        type="business_status",
        assessment_stage="qualification_review",
        failure_effect="qualification_rejection",
        reference_date_type="bid_deadline",
    )

    _validate_semantic_normalization({"requirements": [item]})


def test_local_repair_aligns_stage_with_failure_effect() -> None:
    item = _validated_requirement(
        "낙찰자 결정을 취소합니다.", assessment_stage="bid_entry",
        failure_effect="qualification_rejection",
    )

    _repair_requirement_fields({"requirements": [item]})

    assert item["assessment_stage"] == "qualification_review"
    assert item["review_status"] == "needs_review"
    assert item["confidence"] == 0.7


def test_local_repair_removes_unstated_review_deadline() -> None:
    item = _validated_requirement(
        "입찰참가자격 제한기간 중에 있는 자",
        assessment_stage="qualification_review",
        failure_effect="qualification_rejection",
        reference_date_type="bid_deadline",
    )

    _repair_requirement_fields({"requirements": [item]})

    assert item["reference_date_type"] == "none"


def test_consolidation_keeps_distinct_company_scale_alternatives_from_same_sentence() -> None:
    original = "소기업 또는 소상공인으로서 확인서를 소지한 업체"
    base = _validated_requirement(original, type="company_scale", operator="equals")
    result = {"requirements": [
        {**base, "id": "r1", "value": {**base["value"], "text": "소기업"}},
        {**base, "id": "r2", "value": {**base["value"], "text": "소상공인"}},
    ]}

    _consolidate_requirements(result)

    assert [item["id"] for item in result["requirements"]] == ["r1", "r2"]


def test_semantic_normalization_rejects_unreviewed_source_conflict() -> None:
    first = _validated_requirement("서울특별시 소재 업체", type="participation_region",
                                   operator="in")
    second = _validated_requirement("서울특별시 소재 업체", id="r2",
                                    type="participation_region", operator="not_in")

    with pytest.raises(ValueError, match="conflicting_source_requirements_need_review"):
        _validate_semantic_normalization({"requirements": [first, second]})


def test_citation_validation_rejects_false_coordinates() -> None:
    inputs = {"documents": [{
        "document_id": "doc", "content": {"blocks": [{
            "block_id": "b1", "page": 1, "section": "참가자격",
            "text": "서울특별시 소재 업체",
        }]},
    }], "structured_requirements": []}
    item = _validated_requirement("서울특별시 소재 업체")
    item["evidence"][0].update({"page": 99, "section": "허위절"})

    with pytest.raises(ValueError, match="invalid_document_evidence"):
        _validate_citations({"requirements": [item]}, inputs)


def test_reconciles_summarized_original_text_to_verified_evidence() -> None:
    item = _validated_requirement("정보통신공사업 등록을 필한 업체")
    item["original_text"] = "정보통신공사업 등록 업체"

    _reconcile_original_text({"requirements": [item]})

    assert item["original_text"] == "정보통신공사업 등록을 필한 업체"


def test_postgres_boundary_recursively_removes_nul_characters() -> None:
    value = {"original_text": "입찰\x00자격", "evidence": [{"excerpt": "공동\x00수급"}]}

    assert _sanitize_postgres_value(value) == {
        "original_text": "입찰 자격", "evidence": [{"excerpt": "공동 수급"}]
    }


def test_extraction_summary_marks_flow_failed_when_a_notice_task_fails() -> None:
    with pytest.raises(RuntimeError, match="1 bid eligibility task"):
        _extraction_summary([True, ValueError("invalid_document_evidence")])
    assert _extraction_summary([True, False]).notices == 1


def test_bid_notice_deployments_are_hourly_and_staggered() -> None:
    prefect = yaml.safe_load((PIPELINES / "prefect.yaml").read_text(encoding="utf-8"))
    notices = next(item for item in prefect["deployments"] if item["name"] == "pps-bid-notice-ingestion")
    documents = next(item for item in prefect["deployments"] if item["name"] == "pps-bid-document-processing")
    parsing = next(item for item in prefect["deployments"] if item["name"] == "pps-bid-document-parsing")
    extraction = next(item for item in prefect["deployments"] if item["name"] == "pps-bid-eligibility-extraction")
    retention = next(item for item in prefect["deployments"] if item["name"] == "pps-bid-document-retention")

    assert notices["schedules"][0]["cron"] == "0 * * * *"
    assert documents["schedules"][0]["cron"] == "15 * * * *"
    assert parsing["schedules"][0]["cron"] == "*/10 * * * *"
    assert extraction["schedules"][0]["cron"] == "5-55/10 * * * *"
    assert retention["schedules"][0] == {
        "cron": "45 3 * * *",
        "timezone": "Asia/Seoul",
        "active": True,
    }
    assert retention["parameters"] == {"retention_days": 90, "batch_size": 500}
    assert documents["parameters"] == {"batch_size": 500, "concurrency": 8}
    assert notices["concurrency_limit"]["limit"] == 1
    assert documents["concurrency_limit"]["limit"] == 1
    assert parsing["work_pool"]["name"] == "teoria-ai-extraction"
    assert extraction["work_pool"]["name"] == "teoria-ai-extraction"
    assert sync_pps_bid_notices.name == "나라장터 입찰공고·참가제한 수집"
    assert sync_pps_bid_documents.name == "나라장터 입찰공고 첨부파일 수집"
    assert purge_expired_pps_bid_documents.name == "나라장터 입찰공고 첨부파일 보존기간 삭제"
from datetime import date

from teoria_pipelines.models import CollectionWindow
