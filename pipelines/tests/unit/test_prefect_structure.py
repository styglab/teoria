from inspect import Parameter, signature
import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import yaml
import pytest

from teoria_pipelines.bid_eligibility_expression import compile_eligibility_facts
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
    _bind_standard_rules,
    _consolidate_requirements,
    _ellipsis_fragments_match,
    _reconcile_document_citations,
    _reconcile_original_text,
    _reconcile_proposition_spans,
    _repair_requirement_fields,
    _repair_non_atomic_propositions,
    _repair_requirement_semantics,
    _repair_absorbed_alternative_branches,
    _repair_unresolved_candidates,
    _prune_redundant_aggregate_unresolved,
    _prune_resolved_unresolved_candidates,
    _preserve_certificate_borrowing_invalid_bid,
    _preserve_shared_representative_invalid_bid,
    _preserve_legal_administration_disqualification,
    _preserve_omitted_manual_eligibility,
    _skill_instructions,
    _runtime_extraction_instructions,
    _is_transient_codex_failure,
    _input_fingerprint,
    _prioritize_notices,
    _structured_api_result,
    _structured_license_candidates,
    _hydrate_structured_requirement_attributes,
    _preserve_company_scale_alternatives,
    _prune_unsupported_cross_source_evidence,
    _validate_citations,
    _validate_semantic_normalization,
    extract_bid_eligibility_notice,
    normalize_structured_bid_eligibility_notice,
)


def test_citation_normalization_tolerates_null_model_excerpt() -> None:
    assert _citation_text(None) == ""


def test_standard_rule_binding_uses_normalized_attributes_not_source_text() -> None:
    result = {"requirements": [{
        "type": "certificate",
        "original_text": "원문 명칭은 판정 분기에 사용하지 않는다",
        "value": {"text": "임의 표시", "attributes": [
            {"name": "certificate_type", "value": "direct_production_confirmation"},
            {"name": "product_code", "value": "8111159801"},
        ]},
    }]}

    _bind_standard_rules(result)

    assert result["requirements"][0]["standard_rule_id"] == "holds_valid_direct_production_confirmation"
    assert result["requirements"][0]["rule_arguments"] == {
        "product_code": "8111159801",
    }


def test_company_qualification_types_bind_to_generic_standard_rule() -> None:
    result = {"requirements": [
        {"type": "certificate", "value": {"attributes": [
            {"name": "qualification_type", "value": "women_owned_business"},
        ]}},
        {"type": "certificate", "value": {"attributes": [
            {"name": "qualification_type", "value": "disabled_owned_business"},
        ]}},
    ]}

    _bind_standard_rules(result)

    assert [item["standard_rule_id"] for item in result["requirements"]] == [
        "holds_valid_company_qualification",
        "holds_valid_company_qualification",
    ]
    assert [item["rule_arguments"]["qualification_type"] for item in result["requirements"]] == [
        "women_owned_business",
        "disabled_owned_business",
    ]


def test_standard_rule_binding_covers_company_scale_and_consortium() -> None:
    result = {"requirements": [
        {"type": "company_scale", "value": {
            "text": "소기업", "items": [], "attributes": [],
        }},
        {"type": "consortium", "value": {
            "boolean": False,
            "attributes": [{"name": "participation_mode", "value": "consortium"}],
        }},
    ]}

    _bind_standard_rules(result)

    assert [item["standard_rule_id"] for item in result["requirements"]] == [
        "has_company_scale_qualification",
        "is_consortium_allowed",
    ]


@pytest.mark.parametrize(("text", "qualification_type"), [
    ("벤처기업 확인을 받은 자", "venture_business"),
    ("기술혁신형 중소기업(이노비즈)이어야 한다", "innobiz"),
    ("경영혁신형 중소기업(메인비즈)이어야 한다", "mainbiz"),
])
def test_semantic_repair_normalizes_innovation_company_qualifications(
    text: str, qualification_type: str,
) -> None:
    item = _validated_requirement(text, type="custom")
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)
    _bind_standard_rules(result)

    requirement = result["requirements"][0]
    assert requirement["type"] == "certificate"
    assert requirement["standard_rule_id"] == "holds_valid_company_qualification"
    assert requirement["rule_arguments"] == {"qualification_type": qualification_type}


@pytest.mark.parametrize(("text", "expected_value"), [
    ("소프트웨어사업자(컴퓨터관련서비스사업)로 등록한 자", "소프트웨어사업자(컴퓨터관련서비스사업)"),
    ("소프트웨어사업자(컴퓨터관련서비스사업, 업종코드: 1468)", "1468"),
])
def test_semantic_repair_binds_software_business_to_procurement_industry(
    text: str, expected_value: str,
) -> None:
    item = _validated_requirement(text, type="custom")
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)
    _bind_standard_rules(result)

    requirement = result["requirements"][0]
    assert requirement["type"] == "industry_license"
    assert requirement["standard_rule_id"] == "has_registered_industry"
    assert requirement["standard_rule_version"] == "1.1.0"
    assert requirement["rule_arguments"] == {"expected_value": expected_value}
    assert "industry_registration_type" not in {
        attribute["name"] for attribute in requirement["value"]["attributes"]
    }


def test_status_rules_require_explicit_normalized_subtypes() -> None:
    result = {"requirements": [
        {"type": "procurement_registration", "value": {"attributes": []}},
        {"type": "procurement_registration", "value": {"attributes": [
            {"name": "procurement_registration_type", "value": "supplier_registration"},
        ]}},
        {"type": "business_status", "value": {"attributes": []}},
        {"type": "business_status", "value": {"attributes": [
            {"name": "business_status_type", "value": "active_business_registration"},
        ]}},
        {"type": "sanction", "value": {"attributes": [
            {"name": "period_start", "value": "conviction_finalized_date"},
        ]}},
        {"type": "sanction", "value": {"attributes": [
            {"name": "sanction_type", "value": "procurement_participation_restriction"},
        ]}},
    ]}

    _bind_standard_rules(result)

    assert [item["standard_rule_id"] for item in result["requirements"]] == [
        None,
        "is_registered_procurement_supplier",
        None,
        "is_active_business",
        None,
        "has_no_active_procurement_sanction",
    ]


def test_code_based_rules_prefer_normalized_codes_over_display_text() -> None:
    result = {"requirements": [
        {"type": "industry_license", "value": {
            "text": "기계설비·가스공사업",
            "items": [],
            "attributes": [{"name": "industry_code", "value": "6202"}],
        }},
        {"type": "product_registration", "value": {
            "text": "스크루컨베이어 제조물품 등록",
            "items": [],
            "attributes": [{"name": "product_code", "value": "2410173001"}],
        }},
    ]}

    _bind_standard_rules(result)

    assert result["requirements"][0]["rule_arguments"] == {"expected_value": "6202"}
    assert result["requirements"][1]["rule_arguments"] == {"product_code": "2410173001"}


def test_ambiguous_multi_product_and_post_sanction_period_stay_unbound() -> None:
    result = {"requirements": [
        {
            "type": "certificate",
            "proposition_text": "8014199001 또는 9015189001 직접생산확인증명서를 소지한 업체",
            "value": {"attributes": [
                {"name": "certificate_type", "value": "direct_production_confirmation"},
                {"name": "product_code", "value": "8014199001"},
            ]},
        },
        {
            "type": "sanction",
            "proposition_text": "제재 종료일로부터 3개월이 지나지 아니한 자",
            "value": {"attributes": [
                {"name": "sanction_type", "value": "procurement_participation_restriction"},
            ]},
        },
    ]}

    _bind_standard_rules(result)

    assert [item["standard_rule_id"] for item in result["requirements"]] == [None, None]
from teoria_pipelines.persistence.postgres import (
    _filter_covered_unavailable_documents,
    _sanitize_postgres_value,
    eligibility_requires_review,
)


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
    # Semantic validation failures must not spend tokens by regenerating the whole notice.
    # The scheduler can retry transient failures after the one-hour fingerprint cooldown.
    assert extract_bid_eligibility_notice.retries == 0
    assert extract_bid_eligibility_notice.retry_delay_seconds == 0
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
        "consortiums": [{"sequence": "method", "name": "(없음)공동수급불허"}],
    })
    assert [item["type"] for item in result["requirements"]] == [
        "industry_license", "industry_license", "participation_region", "participation_region",
        "consortium",
    ]
    assert result["expression"]["operator"] == "all"
    assert [branch["operator"] for branch in result["expression"]["conditions"]] == [
        "any", "any", "leaf"
    ]
    consortium = result["requirements"][-1]
    assert consortium["operator"] == "equals"
    assert consortium["value"]["boolean"] is False
    assert all(item["evidence"][0]["source_type"] == "structured_api"
               for item in result["requirements"])


def test_structured_region_rule_prefers_provider_region_code() -> None:
    result = _structured_api_result({
        "licenses": [],
        "regions": [{
            "sequence": "summary", "code": "51", "name": "강원특별자치도",
            "business_type": None, "source_hash": "notice-hash",
        }],
        "consortiums": [],
    })

    _bind_standard_rules(result)

    requirement = result["requirements"][0]
    assert requirement["type"] == "participation_region"
    assert requirement["rule_arguments"] == {"expected_value": "51"}
    assert {item["name"]: item["value"] for item in requirement["value"]["attributes"]} == {
        "region_code": "51", "region_name": "강원특별자치도",
    }


def test_structured_evidence_restores_region_code_before_document_merge() -> None:
    requirement = _validated_requirement("경상남도에 둔 자", type="participation_region")
    requirement["evidence"].append({
        "source_type": "structured_api", "source_id": "region:1",
        "document_id": None, "block_id": None, "page": None, "section": None,
        "excerpt": "경상남도",
    })
    result = {"requirements": [requirement]}

    _hydrate_structured_requirement_attributes(result, {
        "structured_requirements": [{
            "source_id": "region:1", "kind": "participation_region",
            "code": "48", "name": "경상남도",
        }],
    })
    _bind_standard_rules(result)

    assert result["requirements"][0]["rule_arguments"] == {"expected_value": "48"}


def test_structured_api_permitted_industry_has_own_exact_evidence_and_or_branch() -> None:
    license_item = {
            "group": "1", "sequence": "1", "name": "건축공사업/0002",
            "permitted_industries": ["토목건축공사업/0003"],
            "main_fields": None, "business_type": "공사",
        }
    result = _structured_api_result({
        "licenses": [license_item],
        "regions": [],
        "consortiums": [],
    })

    assert [item["original_text"] for item in result["requirements"]] == [
        "건축공사업/0002", "토목건축공사업/0003",
    ]
    assert [item["evidence"][0]["excerpt"] for item in result["requirements"]] == [
        "건축공사업/0002", "토목건축공사업/0003",
    ]
    assert [item["evidence"][0]["source_id"] for item in result["requirements"]] == [
        "license:1:1:primary", "license:1:1:alternative:1",
    ]
    assert result["expression"]["operator"] == "any"
    _validate_citations(result, {
        "documents": [],
        "structured_requirements": _structured_license_candidates(license_item),
    })


def test_structured_api_parses_industry_codes_and_preserves_main_field_logic() -> None:
    result = _structured_api_result({
        "licenses": [{
            "group": "1", "sequence": "1",
            "name": "액화석유가스판매사업/4617",
            "permitted_industries": "[액화석유가스충전사업/4615]",
            "main_fields": "[1^포장공사^보링.그라우팅.파일공사],[2^토공사]",
            "business_type": "공사",
        }],
        "regions": [], "consortiums": [],
    })

    assert result["expression"]["operator"] == "any"
    assert [
        next(attribute["value"] for attribute in item["value"]["attributes"]
             if attribute["name"] == "industry_code")
        for item in result["requirements"]
    ] == ["4617", "4615"]
    main_field_expression = next(
        attribute["value"]
        for attribute in result["requirements"][0]["value"]["attributes"]
        if attribute["name"] == "main_field_expression"
    )
    assert json.loads(main_field_expression) == {
        "operator": "any",
        "conditions": [
            {"sequence": "1", "operator": "all",
             "fields": ["포장공사", "보링.그라우팅.파일공사"]},
            {"sequence": "2", "operator": "all", "fields": ["토공사"]},
        ],
    }
    assert all(item["review_status"] == "needs_review" for item in result["requirements"])


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


def test_final_citation_reconciliation_repairs_evidence_added_after_model_pass() -> None:
    inputs = {"structured_requirements": [], "documents": [{
        "document_id": "doc", "content": {"blocks": [{
            "block_id": "b2", "page": 2, "section": "참가자격",
            "text": "부정당업자 제한기간 중이 아닌 업체",
        }]},
    }]}
    item = _validated_requirement("부정당업자 제한기간 중이 아닌 업체", type="sanction")
    item["evidence"][0].update({
        "document_id": "stale", "source_id": "stale", "block_id": "b1",
        "page": None, "section": None,
    })
    result = {"requirements": [item]}

    _reconcile_document_citations(result, inputs)
    _validate_citations(result, inputs)

    assert item["evidence"][0]["document_id"] == "doc"
    assert item["evidence"][0]["block_id"] == "b2"


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


def test_runtime_extraction_policy_removes_duplicate_skill_overview() -> None:
    skill_root = PIPELINES.parent / ".agents/skills/extract-bid-eligibility"
    with patch("teoria_pipelines.tasks.bid_eligibility.SKILL_ROOT", skill_root):
        full = _skill_instructions()
        runtime = _runtime_extraction_instructions()

    assert len(runtime) < len(full) * 0.75
    assert "Source priority" in runtime
    assert "structured API" in runtime
    assert "qualification_review" in runtime


def test_runtime_prompt_keeps_explicit_eligibility_score_cutoff() -> None:
    source = Path(PIPELINES / "src/teoria_pipelines/tasks/bid_eligibility.py").read_text()

    assert "적격업체 여부를 직접 결정하는 명시적 최저 총점" in source


def test_only_capacity_and_rate_limit_errors_are_transient() -> None:
    assert _is_transient_codex_failure("Selected model is at capacity. Please try again")
    assert _is_transient_codex_failure("429 Too Many Requests: rate limit exceeded")
    assert not _is_transient_codex_failure("invalid output schema")


def test_extraction_fingerprint_changes_with_codex_model(monkeypatch) -> None:
    notice = {
        "notice_hash": "notice-hash", "documents": [], "unavailable_documents": [],
        "licenses": [], "regions": [], "consortiums": [],
    }
    monkeypatch.setenv("TEORIA_CODEX_MODEL", "gpt-5.6-luna")
    luna = _input_fingerprint(notice)
    monkeypatch.setenv("TEORIA_CODEX_MODEL", "gpt-5.6-terra")
    terra = _input_fingerprint(notice)

    assert luna != terra

    monkeypatch.setenv("TEORIA_CODEX_MODEL", "gpt-5.6-luna")
    monkeypatch.setenv("TEORIA_CODEX_FALLBACK_MODEL", "gpt-5.6-terra")
    with_fallback = _input_fingerprint(notice)
    monkeypatch.setenv("TEORIA_CODEX_FALLBACK_MODEL", "gpt-5.6-sol")
    assert with_fallback != _input_fingerprint(notice)


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


def test_semantic_repair_demotes_technician_evaluation_exclusion() -> None:
    text = ("부정당업자로 지정되어 입찰참가 제한기간 중에 있는 업체와 관계법령에 따라 "
            "업무정지 기간 중인 기술자는 당해 평가대상에서 제외한다.")
    item = _validated_requirement(
        text, type="technical_personnel", operator="not_exists",
        value={"text": "업무정지 중인 기술자", "number": None, "boolean": None,
               "items": [], "attributes": []}, comparison_mode="document_evidence",
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []
    assert result["unresolved_candidates"] == [{
        "text": text, "review_reason": "informational_exclusion",
        "blocks_qualification": False,
    }]


def test_semantic_repair_separates_bidder_sanction_from_technician_clause() -> None:
    text = ("본 용역사업 입찰 공고일을 기준하여 평가서 접수마감일 현재 부정당업자 또는 "
            "부실업자로 지정되어 입찰참가 제한기간 중에 있는 업체와 관계법령에 따라 "
            "업무정지 기간 중인 기술자는 당해 평가대상에서 제외한다.")
    item = _validated_requirement(
        text, type="sanction", operator="not_exists",
        value={"text": "입찰참가 제한 중인 업체", "number": None, "boolean": None,
               "items": [], "attributes": []},
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert item["proposition_text"].endswith("업체")
    assert "기술자" not in item["proposition_text"]
    assert text[item["proposition_start"]:item["proposition_end"]] == item["proposition_text"]


def test_non_atomic_sanction_proposition_is_shrunk_to_matching_clause() -> None:
    first = "가. 부정당업자로 입찰참가 제한기간 중인 업체는 참가할 수 없습니다."
    second = "나. 국가계약법 제27조의5에 해당하는 조세포탈 유죄자는 참가할 수 없습니다."
    text = "3. 입찰참가자격\n" + first + "\n" + second + "\n" + ("기타 안내사항 " * 20)
    item = _validated_requirement(
        text, type="sanction", operator="not_exists",
        value={"text": "국가계약법 제27조의5 조세포탈 유죄", "number": None,
               "boolean": False, "items": [], "attributes": []},
        proposition_text=text, proposition_start=0, proposition_end=len(text),
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_non_atomic_propositions(result)

    assert result["requirements"] == [item]
    expected = second.removeprefix("나. ")
    assert item["proposition_text"] == expected
    assert text[item["proposition_start"]:item["proposition_end"]] == expected


def test_ambiguous_expanded_sanction_is_demoted_for_review() -> None:
    text = ("3. 입찰참가자격\n가. 부정당업자는 참가할 수 없습니다.\n"
            "나. 입찰참가 제한 중인 업체는 참가할 수 없습니다.\n" + "안내 " * 60)
    item = _validated_requirement(
        text, type="sanction", operator="not_exists",
        value={"text": "제재 대상", "number": None, "boolean": False,
               "items": [], "attributes": []},
        proposition_text=text, proposition_start=0, proposition_end=len(text),
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_non_atomic_propositions(result)

    assert result["requirements"] == []
    assert result["unresolved_candidates"] == [{
        "text": text, "review_reason": "manual_evidence_interpretation",
        "blocks_qualification": True,
    }]


def test_single_only_and_joint_denial_merge_as_one_common_requirement() -> None:
    first = _validated_requirement(
        "단독이행이 가능해야 합니다.", id="r1", type="consortium",
        operator="exists",
        value={"text": "단독이행 가능", "number": None, "boolean": True,
               "items": [], "attributes": []},
        logic={"placements": [{"scope": "common", "alternative_group": "mode",
                                "alternative_branch": "single"}]},
    )
    second = _validated_requirement(
        "공동수급은 불가합니다.", id="r2", type="consortium",
        operator="not_exists",
        value={"text": "공동수급 불가", "number": None, "boolean": False,
               "items": [], "attributes": []},
        logic={"placements": [{"scope": "common", "alternative_group": "mode",
                                "alternative_branch": "joint"}]},
    )
    result = {"requirements": [first, second], "unresolved_candidates": []}

    _consolidate_requirements(result)

    assert len(result["requirements"]) == 1
    item = result["requirements"][0]
    assert item["operator"] == "not_exists"
    assert item["value"]["text"] == "공동수급 불가"
    assert item["logic"]["placements"] == [{
        "scope": "common", "alternative_group": None, "alternative_branch": None,
    }]
    assert len(item["evidence"]) == 2


def test_semantic_repair_demotes_submission_only_credit_rating() -> None:
    text = ("재정상태 건실도는 신용평가등급을 기준으로 평가(업체 재정자료 최근 연도를 "
            "기준으로 제출) * 미준수 시 평가 불가(탈락처리)")
    item = _validated_requirement(
        text, type="credit_rating", operator="exists",
        value={"text": "신용평가등급", "number": None, "boolean": None,
               "items": [], "attributes": []}, comparison_mode="document_evidence",
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []
    assert result["unresolved_candidates"][0]["review_reason"] == "manual_evidence_interpretation"


def test_semantic_repair_demotes_conditional_credit_history_abuse() -> None:
    text = (
        "신용평가등급을 나라장터에 전송하지 않을 것을 신용정보업자에게 요구·약속하여 "
        "그 이전의 유리한 평가자료를 활용한 업체는 입찰을 무효로 하거나 낙찰자에서 배제한다."
    )
    item = _validated_requirement(
        text, type="credit_rating", operator="not_exists",
        value={"text": "과거 평가자료 부당 활용", "number": None, "boolean": False,
               "items": [], "attributes": []},
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []
    assert result["unresolved_candidates"] == [{
        "text": text,
        "review_reason": "conditional_applicability_unknown",
        "blocks_qualification": True,
    }]


def test_semantic_repair_reclassifies_continued_eligibility() -> None:
    item = _validated_requirement(
        "입찰참가자격은 최종 낙찰 결정 시까지 유지되어야 하며",
        type="sanction", operator="not_exists",
        value={"text": "최종 낙찰 결정 전 입찰참가자격 상실", "number": None,
               "boolean": None, "items": [], "attributes": []},
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert item["type"] == "legal_qualification"
    assert item["operator"] == "valid_on"
    assert item["value"]["boolean"] is True


def test_semantic_repair_prevents_compound_registration_auto_comparison() -> None:
    item = _validated_requirement(
        "업체등록, 인증서 발급, 사용자등록을 마쳐야 합니다.",
        type="procurement_registration", operator="exists",
        value={"text": "전자입찰 등록 절차", "number": None, "boolean": None,
               "items": ["업체등록", "인증서 발급", "사용자등록"], "attributes": []},
        comparison_mode="structured",
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert item["comparison_mode"] == "manual"
    assert item["review_status"] == "needs_review"
    assert result["unresolved_candidates"][0]["blocks_qualification"] is True


def test_semantic_repair_blocks_vague_experience_from_auto_comparison() -> None:
    text = "교복제작 경험과 능력을 갖추고"
    item = _validated_requirement(
        text, type="past_performance", operator="exists",
        value={"text": "교복제작 경험", "number": None, "boolean": None,
               "items": [], "attributes": []}, comparison_mode="document_evidence",
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert item["comparison_mode"] == "manual"
    assert item["review_status"] == "needs_review"
    assert item["confidence"] == 0.7
    assert result["unresolved_candidates"][0]["blocks_qualification"] is True


@pytest.mark.parametrize("text", [
    "사양서대로 제작 및 납품을 할 수 있는 자",
    "판매 후 3년 이상 품질보장(1년간 무상 A/S)이 가능한 자",
])
def test_semantic_repair_blocks_performance_ability_from_auto_comparison(text: str) -> None:
    item = _validated_requirement(text, type="custom", operator="exists",
                                  comparison_mode="structured")
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert item["comparison_mode"] == "manual"
    assert item["review_status"] == "needs_review"
    assert result["unresolved_candidates"][0]["blocks_qualification"] is True


def test_semantic_repair_separates_future_bid_misconduct_from_current_sanction() -> None:
    text = "입찰 참여 사업자간 입찰가격을 담합하는 행위"
    item = _validated_requirement(text, type="sanction", operator="not_exists")
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert item["type"] == "custom"
    assert item["operator"] == "custom"
    assert item["comparison_mode"] == "manual"
    assert item["review_status"] == "needs_review"
    assert result["unresolved_candidates"][0]["blocks_qualification"] is True


def test_semantic_repair_demotes_conditionally_applicable_bidder_succession() -> None:
    text = ("입찰기간 중 의료기기법 제47조에 따라 지위 승계를 마친 업체는 "
            "해당 관련서류를 제출하여 증빙을 받아야 참가자격이 유지됨")
    item = _validated_requirement(text, type="legal_qualification", operator="exists")
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []
    assert result["unresolved_candidates"] == [{
        "text": text, "review_reason": "manual_evidence_interpretation",
        "blocks_qualification": True,
    }]


def test_semantic_repair_demotes_bid_agent_only_alternative_requirements() -> None:
    text = (
        "입찰대리인 경우 법인 등기부등본에 등재된 임원 증명자료 또는 "
        "4대보험 중 어느 하나 가입 증명자료를 제출하여야 하며, "
        "미제출 시 입찰서 무효처리합니다."
    )
    officer = _validated_requirement(
        text, type="legal_qualification", holder_scope="representative",
    )
    insurance = _validated_requirement(
        text, id="r2", type="legal_qualification", holder_scope="representative",
    )
    result = {"requirements": [officer, insurance], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []
    assert result["unresolved_candidates"] == [{
        "text": text, "review_reason": "manual_evidence_interpretation",
        "blocks_qualification": True,
    }]


def test_semantic_repair_keeps_unconditional_representative_requirement() -> None:
    text = "대표자는 입찰마감일까지 개인인증을 완료하여야 합니다."
    item = _validated_requirement(
        text, type="procurement_registration", holder_scope="representative",
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == [item]
    assert result["unresolved_candidates"] == []


def test_semantic_repair_removes_custom_requirement_whose_reference_is_missing() -> None:
    text = "지방자치단체 입찰 및 계약집행기준 제5장 별표1의 배제사유에 해당하지 않는 자"
    item = _validated_requirement(text, type="custom", operator="not_exists")
    result = {"requirements": [item], "unresolved_candidates": [{
        "text": text, "review_reason": "referenced_document_missing",
        "blocks_qualification": True,
    }]}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []
    assert len(result["unresolved_candidates"]) == 1


def test_semantic_repair_removes_typed_requirement_whose_reference_is_missing() -> None:
    text = "국가계약법 제27조 제1항 각 호에 해당하지 않는 업체"
    item = _validated_requirement(text, type="sanction", operator="not_exists")
    result = {"requirements": [item], "unresolved_candidates": [{
        "text": text, "review_reason": "referenced_document_missing",
        "blocks_qualification": True,
    }]}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []


def test_semantic_repair_reclassifies_legal_administration_from_sanction() -> None:
    text = "법정관리 중인 업체는 입찰에 참여할 수 없다"
    item = _validated_requirement(text, type="sanction", operator="not_equals")
    item["value"]["attributes"] = [{
        "name": "sanction_type", "value": "procurement_participation_restriction",
    }]
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert item["type"] == "legal_qualification"
    assert item["comparison_mode"] == "manual"
    assert item["value"]["attributes"] == [{
        "name": "excluded_status", "value": "legal_administration",
    }]


def test_semantic_repair_demotes_reference_only_law_condition() -> None:
    text = "국가계약법 시행령 제 조 및 시행규칙 제 조에 따른 자격요건을 갖춘 업체"
    item = _validated_requirement(text, type="legal_qualification")
    item["review_status"] = "needs_review"
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []
    assert result["unresolved_candidates"] == [{
        "text": text, "review_reason": "referenced_document_missing",
        "blocks_qualification": True,
    }]


def test_semantic_repair_classifies_institutional_debarment_as_manual_sanction() -> None:
    text = "정부출연기관에 의하여 부정당업체로 제재 중인 업체는 참여할 수 없다"
    item = _validated_requirement(text, type="legal_qualification", operator="not_equals")
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert item["type"] == "sanction"
    assert item["comparison_mode"] == "manual"
    assert item["review_status"] == "needs_review"
    assert item["value"]["attributes"] == [{
        "name": "sanction_basis", "value": "institutional_debarment",
    }]


def test_semantic_repair_excludes_post_selection_delivery_orderability() -> None:
    text = (
        "납품 대상 업체 선정 완료 후 실제 납품 요청 시에 나라장터 종합쇼핑몰에서 "
        "주문이 가능하여야 하며 주문이 불가능할 경우 납품 대상 업체가 변경될 수 있습니다."
    )
    item = _validated_requirement(
        text, type="product_registration", operator="valid_on",
        assessment_stage="contracting", failure_effect="cannot_contract",
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []


def test_repair_recovers_shared_representative_simultaneous_bid_invalidity() -> None:
    text = (
        "한 업체의 소속 대표자 중 1인이 다른 업체의 대표자를 겸임할 경우 "
        "해당 업체들이 하나의 입찰에 동시 참여하면 동일인이 2통의 입찰서를 "
        "제출한 것으로 간주되어 모두 무효로 처리됩니다."
    )
    result = {"requirements": [], "unresolved_candidates": [{
        "text": text, "review_reason": "manual_evidence_interpretation",
        "blocks_qualification": True,
    }]}
    inputs = {"documents": [{
        "document_id": "doc", "content": {"blocks": [{
            "block_id": "b1", "page": 2, "section": "입찰의 무효", "text": text,
        }]},
    }]}

    _preserve_shared_representative_invalid_bid(result, inputs)

    assert len(result["requirements"]) == 1
    requirement = result["requirements"][0]
    assert requirement["type"] == "custom"
    assert requirement["operator"] == "not_exists"
    assert requirement["failure_effect"] == "invalid_bid"
    assert requirement["value"]["attributes"] == [{
        "name": "conflict_type",
        "value": "shared_representative_simultaneous_bidding",
    }]
    assert result["unresolved_candidates"] == []


def test_semantic_repair_does_not_treat_personal_business_scope_as_bid_agent_trigger() -> None:
    text = "개인사업자인 경우 사업자등록증상 사업장 소재지가 함안군이어야 합니다."
    item = _validated_requirement(text, type="participation_region")
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == [item]
    assert result["unresolved_candidates"] == []


def test_semantic_repair_blocks_compound_business_status_auto_comparison() -> None:
    text = "청산, 합병, 부도, 워크아웃 또는 회생절차 중인 사업자"
    item = _validated_requirement(
        text, type="business_status", operator="not_in",
        value={"text": None, "number": None, "boolean": None,
               "items": ["청산", "합병", "부도", "워크아웃", "회생절차"],
               "attributes": []}, comparison_mode="structured",
    )
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert item["comparison_mode"] == "manual"
    assert item["review_status"] == "needs_review"
    assert item["confidence"] == 0.7
    assert result["unresolved_candidates"][0]["blocks_qualification"] is True


def test_preserves_omitted_time_bound_manual_ability_gate() -> None:
    clause = ("당사 운영시스템과의 연동 개발작업에 협조하여 "
              "2026년 8월 內까지 가능한 업체(사업 취지에 의거)")
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{"content": {"blocks": [{
        "section": "Ⅱ. 입찰 참가자격", "text": clause,
    }]}}]}

    _preserve_omitted_manual_eligibility(result, inputs)

    assert result["unresolved_candidates"] == [{
        "text": clause, "review_reason": "manual_evidence_interpretation",
        "blocks_qualification": True,
    }]


def test_preserves_omitted_explicit_supplier_registration_gate() -> None:
    clause = (
        "조달청 입찰참가자격 등록된 업체이여야 하며, 조달청 입찰참가자격 미 등록업체는 "
        "조달청 입찰참가자격 등록 규정에 따라 입찰서 제출 마감일 전일까지 등록하여야 합니다."
    )
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{
        "document_id": "doc-1", "content": {"blocks": [{
            "block_id": "b1", "page": None, "section": "참가자격", "text": clause,
        }]},
    }]}

    _preserve_omitted_manual_eligibility(result, inputs)

    requirement = result["requirements"][0]
    assert requirement["type"] == "procurement_registration"
    assert requirement["reference_date_type"] == "qualification_registration_deadline"
    assert requirement["value"]["attributes"] == [{
        "name": "procurement_registration_type", "value": "supplier_registration",
    }]
    assert requirement["evidence"][0]["excerpt"] == clause


def test_does_not_turn_generic_electronic_contract_registration_into_supplier_gate() -> None:
    clause = "전자계약 참가자격 미 등록업체는 국가종합전자조달시스템에 이용자 등록을 하여야 합니다."
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{"document_id": "doc", "content": {"blocks": [{
        "block_id": "b1", "page": 1, "section": "계약", "text": clause,
    }]}}]}

    _preserve_omitted_manual_eligibility(result, inputs)

    assert result["requirements"] == []


def test_preserves_compact_g2b_bid_registration_gate() -> None:
    clause = (
        "입찰서 제출 마감일 전일까지 나라장터 시스템(G2B)에 "
        "입찰참가등록을 필한 업체"
    )
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{"document_id": "doc", "content": {"blocks": [{
        "block_id": "b1", "page": 1, "section": None,
        "text": "입찰 참가자격\n" + clause,
    }]}}]}

    _preserve_omitted_manual_eligibility(result, inputs)

    assert len(result["requirements"]) == 1
    assert result["requirements"][0]["type"] == "procurement_registration"
    assert result["requirements"][0]["reference_date_type"] == (
        "qualification_registration_deadline"
    )


def test_preserves_omitted_explicit_tax_evasion_disqualification() -> None:
    clause = (
        "조세포탈 등을 한 자로서 유죄판결이 확정된 날부터 2년이 지나지 "
        "아니한 자는 입찰에 참여할 수 없음"
    )
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{"document_id": "doc", "content": {"blocks": [{
        "block_id": "b1", "page": 2, "section": None,
        "text": "입찰 참가자격\n" + clause,
    }]}}]}

    _preserve_omitted_manual_eligibility(result, inputs)

    requirement = result["requirements"][0]
    assert requirement["type"] == "sanction"
    assert requirement["operator"] == "not_exists"
    assert requirement["evidence"][0]["excerpt"] == clause


def test_preserves_omitted_explicit_equipment_ownership_gate() -> None:
    clause = (
        "2. 입찰참가자격\n"
        "◦ 「8도 이상 인쇄기」 2대 이상을 보유하고 금융결제원 등록 "
        "지로장표 적격인쇄 승인을 받은 자"
    )
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{"document_id": "doc", "content": {"blocks": [{
        "block_id": "b1", "page": 1, "section": None, "text": clause,
    }]}}]}

    _preserve_omitted_manual_eligibility(result, inputs)

    requirement = result["requirements"][0]
    assert requirement["type"] == "equipment_ownership"
    assert requirement["operator"] == "greater_than_or_equal"
    assert requirement["value"]["number"] == 2
    assert requirement["value"]["text"] == "8도 이상 인쇄기 2대 이상 보유"
    assert requirement["evidence"][0]["excerpt"] == "「8도 이상 인쇄기」 2대 이상을 보유"


def test_does_not_turn_equipment_specification_into_ownership_gate() -> None:
    clause = "규격서: 냉난방기는 실외기 2대 이상을 포함하여 설치하여야 한다."
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{"document_id": "doc", "content": {"blocks": [{
        "block_id": "b1", "page": 1, "section": "규격", "text": clause,
    }]}}]}

    _preserve_omitted_manual_eligibility(result, inputs)

    assert result["requirements"] == []


def test_preserves_omitted_bankruptcy_gates_at_bid_and_contract_stages() -> None:
    clause = (
        "부도 또는 파산 상태에 있는 업체는 본 입찰에 참가할 수 없으며, "
        "낙찰 후 계약 체결 전에 부도 또는 파산상태에 있는 업체인 경우 "
        "계약체결대상에서 제외함"
    )
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{"document_id": "doc", "content": {"blocks": [{
        "block_id": "p2", "page": 2, "section": "참가자격", "text": clause,
    }]}}]}

    _preserve_omitted_manual_eligibility(result, inputs)

    assert [(item["type"], item["assessment_stage"], item["failure_effect"])
            for item in result["requirements"]] == [
        ("business_status", "bid_entry", "cannot_bid"),
        ("business_status", "contracting", "cannot_contract"),
    ]
    assert all(item["operator"] == "not_exists" for item in result["requirements"])
    assert all(item["evidence"][0]["excerpt"] in clause
               for item in result["requirements"])


def test_does_not_turn_informational_bankruptcy_reference_into_gate() -> None:
    clause = "제안서에는 부도 또는 파산 관련 통계자료를 참고자료로 첨부할 수 있습니다."
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{"document_id": "doc", "content": {"blocks": [{
        "block_id": "b1", "page": 1, "section": "참고자료", "text": clause,
    }]}}]}

    _preserve_omitted_manual_eligibility(result, inputs)

    assert result["requirements"] == []


def test_citation_text_accepts_numeric_model_excerpt() -> None:
    assert _citation_text(85) == "85"


def test_repair_normalizes_explicit_negative_sanction_state() -> None:
    item = _validated_requirement(
        "부정당업체로 지정되지 않은 업체", type="sanction", operator="not_equals",
    )
    item["value"]["text"] = "부정당업체 지정 상태"

    _repair_requirement_fields({"requirements": [item]})

    assert item["operator"] == "not_exists"


def test_repair_does_not_apply_registration_deadline_to_general_legal_status() -> None:
    item = _validated_requirement(
        "입찰참가 업체등록을 마친 업체로서 국가계약법령상 경쟁입찰 참가자격을 갖추어야 함",
        type="legal_qualification",
        reference_date_type="qualification_registration_deadline",
    )
    item["proposition_text"] = "국가계약법령상 경쟁입찰 참가자격을 갖추어야 함"
    item["proposition_start"] = item["original_text"].index(item["proposition_text"])
    item["proposition_end"] = item["proposition_start"] + len(item["proposition_text"])

    _repair_requirement_fields({"requirements": [item]})

    assert item["reference_date_type"] == "bid_deadline"


def test_repair_classifies_statutory_general_bid_qualification() -> None:
    item = _validated_requirement(
        "국가계약법 시행령 제12조 및 시행규칙 제14조에 따른 소정의 자격",
        type="custom",
    )

    _repair_requirement_semantics({"requirements": [item], "unresolved_candidates": []})

    assert item["type"] == "legal_qualification"


def test_repair_classifies_manufacturer_authorized_dealer() -> None:
    item = _validated_requirement("해당 설비 제조사 또는 대리점", type="custom")

    _repair_requirement_semantics({"requirements": [item], "unresolved_candidates": []})

    assert item["type"] == "manufacturer_status"


def test_repair_classifies_dealer_with_manufacturer_distribution_agreement() -> None:
    item = _validated_requirement(
        "의료기기 업체 및 제조원과의 판권계약이 체결된 국내 대리점 또는 지사",
        type="custom",
    )

    _repair_requirement_semantics({"requirements": [item], "unresolved_candidates": []})

    assert item["type"] == "manufacturer_status"


def test_repair_classifies_institution_retiree_conflict_gate() -> None:
    item = _validated_requirement(
        "기관 퇴직자가 설립했거나 등기임원으로 재취업 중인 업체의 입찰은 무효",
        type="custom", operator="not_exists", failure_effect="invalid_bid",
    )

    _repair_requirement_semantics({"requirements": [item], "unresolved_candidates": []})

    assert item["type"] == "legal_qualification"


def test_repair_normalizes_subcontracting_prohibition_operator() -> None:
    item = _validated_requirement(
        "본 사업은 하도급 계약을 불허합니다", type="consortium",
        operator="not_equals",
    )

    _repair_requirement_fields({"requirements": [item]})

    assert item["operator"] == "not_exists"


def test_repair_normalizes_active_tax_evasion_disqualification_operator() -> None:
    item = _validated_requirement(
        "조세포탈 등을 한 자로서 유죄판결 확정일부터 2년이 지나지 않은 자는 입찰에 참여할 수 없다",
        type="sanction", operator="not_equals",
    )

    _repair_requirement_fields({"requirements": [item]})

    assert item["operator"] == "not_exists"


@pytest.mark.parametrize("clause", [
    "입찰참가자격 제한기간 중에 있는 자",
    "부정당업자 제재 종료 후 3개월이 지나지 아니한 자",
])
def test_repair_normalizes_any_negative_sanction_state(clause: str) -> None:
    item = _validated_requirement(clause, type="sanction", operator="not_equals")

    _repair_requirement_fields({"requirements": [item]})

    assert item["operator"] == "not_exists"


def test_repair_consortrium_prohibition_sets_single_only_mode() -> None:
    item = _validated_requirement(
        "공동수급은 허용하지 않습니다", type="consortium", operator="not_exists",
    )
    item["value"]["attributes"] = [
        {"name": "participation_mode", "value": "consortium"},
    ]

    _repair_requirement_fields({"requirements": [item]})

    assert item["value"]["attributes"] == [
        {"name": "participation_mode", "value": "single_only"},
    ]


@pytest.mark.parametrize("clause", [
    "공동수급체 중복결성은 금지합니다",
    "발주자 동의 없는 하도급은 금지합니다",
])
def test_repair_does_not_mark_non_participation_prohibition_single_only(clause: str) -> None:
    item = _validated_requirement(clause, type="consortium", operator="not_exists")
    item["value"]["attributes"] = [
        {"name": "participation_mode", "value": "single_only"},
    ]

    _repair_requirement_fields({"requirements": [item]})

    assert item["value"]["attributes"] == []


def test_repair_drops_personal_certificate_fingerprint_exception_as_required_fact() -> None:
    clause = (
        "지문인식 신원확인이 곤란한 자는 예외적으로 개인인증서에 의한 "
        "전자견적서 제출이 가능합니다."
    )
    item = _validated_requirement(clause, type="procurement_registration")
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []
    assert result["unresolved_candidates"] == []


def test_repair_drops_wrapped_personal_certificate_exception_by_semantic_attribute() -> None:
    clause = (
        "다만, 지문인식 신원확인 입찰이 곤란한 자는 규정된 절차에 따라 예\n"
        "외적으로 개인인증서에 의한 전자입찰서 제출이 가능합니다."
    )
    item = _validated_requirement(
        clause, type="procurement_registration", operator="custom",
    )
    item["value"]["attributes"] = [
        {"name": "authentication_method", "value": "personal_certificate_exception"},
    ]
    result = {"requirements": [item], "unresolved_candidates": []}

    _repair_requirement_semantics(result)

    assert result["requirements"] == []


def test_repair_normalizes_tax_evasion_list_exclusion_without_inline_effect() -> None:
    item = _validated_requirement(
        "‘조세포탈 등을 한 자’로서 유죄판결이 확정된 날부터 2년이 지나지 아니한 자",
        type="sanction", operator="not_equals",
    )

    _repair_requirement_fields({"requirements": [item]})

    assert item["operator"] == "not_exists"


def test_repair_normalizes_subcontracting_unavailable_operator() -> None:
    item = _validated_requirement(
        "하도급 불가", type="consortium", operator="equals",
    )

    _repair_requirement_fields({"requirements": [item]})

    assert item["operator"] == "not_exists"


@pytest.mark.parametrize("clause", [
    "평가위원들의 종합평점이 100점 만점에 85점 이상을 득한 업체를 규격입찰 적격업체로 선정하되",
    "기술능력평가 분야 배점한도의 85% 이상인 자 중 종합평가점수가 높은 업체부터 협상 실시",
])
def test_preserves_explicit_eligibility_score_threshold(clause: str) -> None:
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{"document_id": "doc", "content": {"blocks": [{
        "block_id": "b1", "page": 1, "section": "평가", "text": clause,
    }]}}]}

    _preserve_omitted_manual_eligibility(result, inputs)

    requirement = result["requirements"][0]
    assert requirement["type"] == "custom"
    assert requirement["operator"] == "greater_than_or_equal"
    assert requirement["assessment_stage"] == "qualification_review"
    assert requirement["failure_effect"] == "qualification_rejection"
    assert requirement["value"]["number"] == 85


def test_does_not_turn_individual_proposal_score_into_eligibility_threshold() -> None:
    clause = "사업이해도 평가항목은 100점 만점 중 85점을 배점한다."
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{"document_id": "doc", "content": {"blocks": [{
        "block_id": "b1", "page": 1, "section": "평가항목", "text": clause,
    }]}}]}

    _preserve_omitted_manual_eligibility(result, inputs)

    assert result["requirements"] == []


def test_preserves_omitted_borrowed_certificate_invalid_bid_condition() -> None:
    clause = (
        "1인이 수인의 공인인증서를 차용하여 입찰서를 제출할 경우\n"
        "- 당해 입찰은 관련 규정에 따라 무효인 입찰에 해당되며"
    )
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{"document_id": "doc-1", "content": {"blocks": [{
        "block_id": "p1b14", "page": 1, "section": "기타 참고사항", "text": clause,
    }]}}]}

    _preserve_certificate_borrowing_invalid_bid(result, inputs)

    requirement = result["requirements"][0]
    assert requirement["type"] == "procurement_registration"
    assert requirement["assessment_stage"] == "bid_entry"
    assert requirement["failure_effect"] == "invalid_bid"
    assert requirement["comparison_mode"] == "manual"
    assert requirement["original_text"] == clause


def test_submission_checklist_without_failure_effect_is_nonblocking() -> None:
    result = {"unresolved_candidates": [{
        "text": "사업자등록증 사본, 법인등기부등본, 인감증명서 각 1부",
        "review_reason": "manual_evidence_interpretation", "blocks_qualification": True,
    }]}

    _repair_unresolved_candidates(result)

    assert result["unresolved_candidates"][0]["review_reason"] == "informational_exclusion"
    assert result["unresolved_candidates"][0]["blocks_qualification"] is False


def test_submission_clause_with_explicit_omission_effect_remains_blocking() -> None:
    result = {"unresolved_candidates": [{
        "text": "사업자등록증 미제출 시 입찰 참여 자격이 상실됩니다.",
        "review_reason": "manual_evidence_interpretation", "blocks_qualification": True,
    }]}

    _repair_unresolved_candidates(result)

    assert result["unresolved_candidates"][0]["blocks_qualification"] is True


def test_post_selection_delivery_condition_is_nonblocking_in_unresolved() -> None:
    result = {"unresolved_candidates": [{
        "text": (
            "납품 대상 업체 선정 완료 후 실제 납품 요청 시 나라장터 종합쇼핑몰에서 "
            "주문이 가능해야 하며 불가능하면 납품 대상 업체가 변경됩니다."
        ),
        "review_reason": "ambiguous_stage", "blocks_qualification": True,
    }]}

    _repair_unresolved_candidates(result)

    assert result["unresolved_candidates"][0] == {
        "text": result["unresolved_candidates"][0]["text"],
        "review_reason": "informational_exclusion",
        "blocks_qualification": False,
    }


def test_general_law_violation_invalidity_is_missing_reference() -> None:
    result = {"unresolved_candidates": [{
        "text": "계약자 선정 시 지방계약법 등에 위배되었을 경우 무효로 합니다.",
        "review_reason": "manual_evidence_interpretation",
        "blocks_qualification": True,
    }]}

    _repair_unresolved_candidates(result)

    assert result["unresolved_candidates"][0]["review_reason"] == "referenced_document_missing"


def test_shared_representative_invalid_requirement_removes_duplicate_unresolved() -> None:
    atom = (
        "한 업체의 소속 대표자 중 1인이 다른 업체의 대표자를 겸임할 경우 "
        "해당 업체들이 동시에 참여하면 모두 무효입니다."
    )
    requirement = _validated_requirement(
        atom, type="legal_qualification", operator="not_equals",
        failure_effect="invalid_bid",
    )
    result = {"requirements": [requirement], "unresolved_candidates": [{
        "text": "입찰 무효 안내: " + atom + " 관련 내용을 확인하십시오.",
        "review_reason": "manual_evidence_interpretation",
        "blocks_qualification": True,
    }]}

    _repair_unresolved_candidates(result)

    assert result["unresolved_candidates"] == []


def test_exact_manual_unresolved_duplicate_of_atomic_requirement_is_removed() -> None:
    text = "국세 및 지방세 체납 중인 업체는 입찰에 참여할 수 없다."
    result = {
        "requirements": [_validated_requirement(
            text, type="legal_qualification", operator="not_equals",
        )],
        "unresolved_candidates": [{
            "text": text, "review_reason": "manual_evidence_interpretation",
            "blocks_qualification": True,
        }],
    }

    _prune_resolved_unresolved_candidates(result)

    assert result["unresolved_candidates"] == []


def test_missing_reference_is_not_pruned_even_if_requirement_duplicates_it() -> None:
    text = "별표1의 배제사유에 해당하지 않는 자"
    result = {
        "requirements": [_validated_requirement(text, type="custom")],
        "unresolved_candidates": [{
            "text": text, "review_reason": "referenced_document_missing",
            "blocks_qualification": True,
        }],
    }

    _prune_resolved_unresolved_candidates(result)

    assert len(result["unresolved_candidates"]) == 1


def test_aggregate_unresolved_keeps_only_unrepresented_bullet() -> None:
    represented = _validated_requirement("입찰참가 등록한 업체")
    text = (
        "4. 입찰참가자격의 상세 조건을 아래와 같이 안내하며 모든 조건을 갖추어야 합니다. "
        "관련 규정과 증빙자료를 반드시 확인하십시오.\n"
        " ◦ 입찰참가 등록한 업체\n"
        " ◦ 동등한 자격요건을 갖춘 업체"
    ) + " 확인 안내" * 40
    result = {"requirements": [represented], "unresolved_candidates": [{
        "text": text, "review_reason": "manual_evidence_interpretation",
        "blocks_qualification": True,
    }]}

    _prune_redundant_aggregate_unresolved(result)

    assert result["unresolved_candidates"] == [{
        "text": "동등한 자격요건을 갖춘 업체" + " 확인 안내" * 40,
        "review_reason": "manual_evidence_interpretation",
        "blocks_qualification": True,
    }]


def test_repair_recovers_legal_administration_from_compound_exclusion() -> None:
    text = (
        "다. 법정관리 중이거나 국가 지방자치단체 정부출연기관 및 투자기관에 의하여 "
        "부정당업체로 제재 중인 업체는 참여할 수 없다"
    )
    result = {"requirements": [], "unresolved_candidates": []}
    inputs = {"documents": [{
        "document_id": "doc", "content": {"blocks": [{
            "block_id": "b1", "page": 2, "section": "입찰참가자격", "text": text,
        }]},
    }]}

    _preserve_legal_administration_disqualification(result, inputs)

    assert len(result["requirements"]) == 1
    requirement = result["requirements"][0]
    assert requirement["operator"] == "not_equals"
    assert requirement["value"]["attributes"] == [{
        "name": "excluded_status", "value": "legal_administration",
    }]
    assert requirement["failure_effect"] == "cannot_bid"


def test_unavailable_renditions_are_covered_transitively_by_parsed_pdf() -> None:
    documents = [("pdf", "공고문.pdf", "pdf-checksum", "parsed-key")]
    unavailable = [
        ("hwp", "공고문.hwp", "stored", 3, None, "unsupported", 3, "failed", "hwp-checksum"),
        ("standard", "표준공고서", "stored", 3, None, "unsupported", 3, "failed", "hwp-checksum"),
        ("other", "별첨.hwp", "stored", 3, None, "unsupported", 3, "failed", "other-checksum"),
    ]

    assert _filter_covered_unavailable_documents(documents, unavailable) == [unavailable[2]]


def test_semantic_repair_simplifies_absorbed_alternative_conservatively() -> None:
    original = "중간처리업과 수집운반업 면허 보유자 또는 중간처리업 면허 보유자"
    intermediate = _validated_requirement(original, type="industry_license")
    intermediate["logic"] = {"placements": [
        {"scope": "single", "alternative_group": "license", "alternative_branch": "both"},
        {"scope": "single", "alternative_group": "license", "alternative_branch": "intermediate"},
    ]}
    transport = _validated_requirement(original, id="r2", type="industry_license")
    transport["logic"] = {"placements": [
        {"scope": "single", "alternative_group": "license", "alternative_branch": "both"},
    ]}
    result = {"requirements": [intermediate, transport], "unresolved_candidates": []}

    _repair_absorbed_alternative_branches(result)

    assert [item["id"] for item in result["requirements"]] == ["r1"]
    assert result["requirements"][0]["logic"]["placements"] == [{
        "scope": "single", "alternative_group": "license",
        "alternative_branch": "intermediate",
    }]
    assert result["unresolved_candidates"] == [{
        "text": original, "review_reason": "manual_evidence_interpretation",
        "blocks_qualification": True,
    }]


def test_consolidation_keeps_distinct_company_scale_alternatives_from_same_sentence() -> None:
    original = "소기업 또는 소상공인으로서 확인서를 소지한 업체"
    base = _validated_requirement(original, type="company_scale", operator="equals")
    result = {"requirements": [
        {**base, "id": "r1", "value": {**base["value"], "text": "소기업"}},
        {**base, "id": "r2", "value": {**base["value"], "text": "소상공인"}},
    ]}

    _consolidate_requirements(result)

    assert [item["id"] for item in result["requirements"]] == ["r1", "r2"]


def test_repair_recovers_missing_company_scale_or_branch_from_document() -> None:
    clause = (
        "중소기업제품 구매촉진 및 판로지원에 관한 법률에 따른 소기업 확인서 또는\n"
        "소상공인 보호 및 지원에 관한 법률에 따른 소상공인 확인서를 소지한 업체"
    )
    existing = _validated_requirement(
        "소상공인 확인서를 소지한 업체", type="company_scale", operator="equals"
    )
    existing["value"]["text"] = "소상공인"
    existing["evidence"][0].update({
        "source_id": "doc", "document_id": "doc", "block_id": "b1",
        "excerpt": "소상공인 확인서를 소지한 업체",
    })
    result = {"requirements": [existing], "unresolved_candidates": []}
    inputs = {"documents": [{
        "document_id": "doc", "content": {"blocks": [{
            "block_id": "b1", "page": 1, "section": "입찰참가자격", "text": clause,
        }]},
    }]}

    _preserve_company_scale_alternatives(result, inputs)
    compiled = compile_eligibility_facts(result)

    assert {item["value"]["text"] for item in result["requirements"]} == {
        "소기업", "소상공인",
    }
    assert compiled["expression"]["operator"] == "any"
    assert {item["requirement_id"] for item in compiled["expression"]["conditions"]} == {
        "r1", "r2",
    }
    assert {
        next(attribute["value"] for attribute in item["value"]["attributes"]
             if attribute["name"] == "company_scale_type")
        for item in result["requirements"]
    } == {"small_enterprise", "small_business_owner"}


def test_api_only_industry_alternative_drops_unsupported_document_evidence() -> None:
    item = _validated_requirement(
        "의약품판매업(의약품도매상)/5307", type="industry_license", operator="equals"
    )
    item["value"]["attributes"] = [
        {"name": "industry_name", "value": "의약품판매업(의약품도매상)"},
        {"name": "industry_code", "value": "5307"},
    ]
    item["evidence"] = [
        {"source_type": "document", "source_id": "doc", "document_id": "doc",
         "block_id": "b1", "page": 1, "section": "입찰참가자격",
         "excerpt": "의료기기 제조업 5309 또는 의료기기 수입업 5310"},
        {"source_type": "structured_api", "source_id": "license:3:3:alternative:1",
         "document_id": None, "block_id": None, "page": None, "section": None,
         "excerpt": "의약품판매업(의약품도매상)/5307"},
    ]
    result = {"requirements": [item]}

    _prune_unsupported_cross_source_evidence(result)

    assert [evidence["source_type"] for evidence in item["evidence"]] == ["structured_api"]


def test_redundant_whole_eligibility_section_is_removed_from_unresolved() -> None:
    first = _validated_requirement("입찰참가 등록한 업체")
    second = _validated_requirement("의료기기 제조업 등록 업체", id="r2")
    result = {
        "requirements": [first, second],
        "unresolved_candidates": [{
            "text": (
                "4. 입찰참가자격(다음 각 호를 모두 갖춘 업체)\n"
                " ◦ 입찰참가 등록한 업체\n"
                " ◦ 의료기기 제조업 등록 업체"
            ) * 5,
            "review_reason": "manual_evidence_interpretation",
            "blocks_qualification": True,
        }],
    }

    _prune_redundant_aggregate_unresolved(result)

    assert result["unresolved_candidates"] == []


def test_aggregate_coverage_uses_normalized_value_when_canonical_source_is_api() -> None:
    industry = _validated_requirement(
        "의료기기제조업/5309", type="industry_license", operator="equals"
    )
    industry["value"].update({"text": "의료기기제조업", "attributes": [
        {"name": "industry_code", "value": "5309"},
    ]})
    registration = _validated_requirement("입찰참가 등록한 업체", id="r2")
    aggregate = (
        "4. 입찰참가자격 안내문입니다. 상세한 자격은 다음 각 호와 같으며 "
        "각 조건을 모두 확인하여야 합니다.\n"
        " ◦ 입찰참가 등록한 업체\n"
        " ◦ 의료기기 제조업(업종코드 5309) 등록 업체"
    )
    aggregate += " 자격 확인 안내" * 20
    result = {"requirements": [industry, registration], "unresolved_candidates": [{
        "text": aggregate, "review_reason": "manual_evidence_interpretation",
        "blocks_qualification": True,
    }]}

    _prune_redundant_aggregate_unresolved(result)

    assert result["unresolved_candidates"] == []


def test_consolidation_keeps_shortest_verbatim_original_text() -> None:
    short = _validated_requirement("입찰참가등록사항을 변경등록하지 않은 입찰은 무효")
    long = {**short, "id": "r2", "original_text": (
        "이전 페이지의 무관한 문장. 입찰참가등록사항을 변경등록하지 않은 입찰은 무효. "
        "다음 절의 무관한 문장"
    )}
    result = {"requirements": [long, short]}

    _consolidate_requirements(result)

    assert result["requirements"][0]["original_text"] == short["original_text"]


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


def test_reconcile_original_text_uses_exact_evidence_when_whitespace_differs() -> None:
    original = "입찰참가자격 제한을 통보받았거나 전자조달시스템에 게재된 자"
    item = _validated_requirement(original)
    excerpt = (
        "입찰참가자격 제한을 통보 받았거나  전자조달시스템에 게재된 자"
    )
    item["evidence"][0]["excerpt"] = excerpt

    _reconcile_original_text({"requirements": [item]})

    assert item["original_text"] == excerpt
    _reconcile_proposition_spans({"requirements": [item]})
    _validate_semantic_normalization({"requirements": [item]})


def test_postgres_boundary_recursively_removes_nul_characters() -> None:
    value = {"original_text": "입찰\x00자격", "evidence": [{"excerpt": "공동\x00수급"}]}

    assert _sanitize_postgres_value(value) == {
        "original_text": "입찰 자격", "evidence": [{"excerpt": "공동 수급"}]
    }


def test_extraction_summary_marks_flow_failed_when_a_notice_task_fails() -> None:
    with pytest.raises(RuntimeError, match="1 bid eligibility task"):
        _extraction_summary([True, ValueError("invalid_document_evidence")])
    assert _extraction_summary([True, False]).notices == 1


@pytest.mark.asyncio
async def test_write_free_extraction_never_persists_outputs_or_failures() -> None:
    store = MagicMock()
    storage = MagicMock()
    storage.get_bytes.return_value = json.dumps({
        "blocks": [{"block_id": "b1", "page": 1, "section": "안내", "text": "일반 안내"}],
    }).encode()
    settings = MagicMock(bid_eligibility_input_max_chars=120_000)
    notice = {
        "notice_number": "sample", "notice_order": "000", "notice_hash": "hash",
        "bid_deadline_at": None,
        "documents": [{
            "document_id": "doc", "file_name": "공고문.pdf", "checksum": "checksum",
            "parsed_object_key": "parsed.json",
        }],
        "unavailable_documents": [], "licenses": [], "regions": [], "consortiums": [],
        "coverage": {
            "completeness": "complete", "requires_review": False,
            "total_document_count": 1, "parsed_document_count": 1,
            "unavailable_document_count": 0, "structured_requirement_count": 0,
        },
    }
    process = CompletedProcess(
        args=[], returncode=0,
        stdout=json.dumps({
            "schema_version": "1.4.0", "requirements": [], "unresolved_candidates": [],
        }), stderr="",
    )
    skill_root = PIPELINES.parent / ".agents/skills/extract-bid-eligibility"
    with (
        patch("teoria_pipelines.tasks.bid_eligibility._resources", return_value=(store, storage)),
        patch("teoria_pipelines.tasks.bid_eligibility.bootstrap_pipeline_settings",
              return_value=settings),
        patch("teoria_pipelines.tasks.bid_eligibility.subprocess.run", return_value=process),
        patch("teoria_pipelines.tasks.bid_eligibility.SKILL_ROOT", skill_root),
    ):
        result = await extract_bid_eligibility_notice.fn(notice, persist=False)

    assert result["requirements"] == []
    store.save_eligibility_failure.assert_not_called()
    store.save_eligibility_extraction.assert_not_called()
    storage.put_bytes.assert_not_called()


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
