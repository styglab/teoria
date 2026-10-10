from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from teoria.registry.loader import RegistryLoader
from teoria.runtime.capability.runner import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.market_context.processor import (
    _contract_time_relationship,
    _contract_family_summary,
    _decorate_contract_lineage,
    _build_attention_suppliers,
    _organization_field_event_analysis,
    _industry_license_eligibility,
    execute_bid_project_lineage,
    execute_bid_notice_relationship_context,
    execute_bid_notice_participations,
    execute_bid_participation_context,
    execute_bid_related_projects_search,
    execute_company_procurement_profile,
    execute_organization_procurement_profile,
    execute_organization_supplier_entry_search,
    execute_company_participation_search,
    execute_company_competitor_analysis,
    execute_organization_company_field_relationship,
    execute_organization_company_relationship,
    execute_company_similar_project_experience,
    enrich_contract_search_objects,
    execute_procurement_outcome_search,
    execute_procurement_activity_search,
)
from teoria.runtime.provenance import Provenance


REGISTRIES = Path(__file__).parents[3] / "registries"


def test_contract_lineage_marks_repeated_inferred_phase_as_amendment() -> None:
    contracts = []
    for event_id, name, event_date in (
        ("ORIGINAL", "장기 사업(총괄)", date(2024, 1, 1)),
        ("PHASE-5", "장기 사업(5차)", date(2024, 2, 1)),
        ("PHASE-5-CHANGE", "장기 사업(5차)", date(2024, 3, 1)),
    ):
        contracts.append({
            "contract_event_id": event_id,
            "first_contract_date": event_date,
            "current_contract_amount": 100,
            "_lineage_source": {
                "unified_contract_number": f"U-{event_id}",
                "confirmed_contract_number": event_id,
                "contract_reference_number": event_id,
                "contract_name": name,
                "long_term_continuation_type": "장기",
                "total_amount": 300,
            },
        })

    _decorate_contract_lineage(contracts, bid_notice_id="NOTICE:000")

    by_id = {item["contract_event_id"]: item for item in contracts}
    assert by_id["ORIGINAL"]["contract_record_type"] == "original"
    assert by_id["PHASE-5"]["contract_record_type"] == "phase"
    assert by_id["PHASE-5"]["parent_contract_event_id"] == "ORIGINAL"
    assert by_id["PHASE-5-CHANGE"]["contract_record_type"] == "amendment"
    assert by_id["PHASE-5-CHANGE"]["parent_contract_event_id"] == "PHASE-5"
    assert by_id["PHASE-5-CHANGE"]["relationship_status"] == "inferred"


def test_contract_lineage_uses_official_change_order_and_latest_total() -> None:
    contracts = []
    for event_id, order, event_date, amount in (
        ("R25TA0088012800", "00", date(2025, 9, 12), 443_000_000),
        ("R25TA0088012801", "01", date(2026, 6, 1), 651_713_320),
    ):
        contracts.append({
            "contract_event_id": event_id,
            "first_contract_date": event_date,
            "current_contract_amount": amount,
            "_lineage_source": {
                "unified_contract_number": f"UNIFIED-{order}",
                "confirmed_contract_number": event_id,
                "contract_reference_number": event_id,
                "contract_name": "산재근로자 내일찾기플랫폼 고도화 및 메타버스 유지보수",
                "long_term_continuation_type": "신규",
                "total_amount": 0,
                "contract_detail_url": (
                    "https://www.g2b.go.kr/link/FIUA027_01/single/"
                    f"?ctrtNo=R25TA00880128&ctrtChgOrd={order}"
                ),
            },
        })

    _decorate_contract_lineage(
        contracts, bid_notice_id="R25BK01012988:000",
    )

    by_id = {item["contract_event_id"]: item for item in contracts}
    original = by_id["R25TA0088012800"]
    amendment = by_id["R25TA0088012801"]
    assert original["contract_family_id"] == amendment["contract_family_id"]
    assert original["contract_record_type"] == "original"
    assert original["is_current_record"] is False
    assert original["superseded_by_contract_event_id"] == "R25TA0088012801"
    assert original["amount_record_type"] == "initial_total"
    assert original["total_contract_amount"] == 443_000_000
    assert original["include_in_family_total"] is False
    assert amendment["contract_record_type"] == "amendment"
    assert amendment["parent_contract_event_id"] == "R25TA0088012800"
    assert amendment["original_contract_event_id"] == "R25TA0088012800"
    assert amendment["is_current_record"] is True
    assert amendment["amount_record_type"] == "current_total"
    assert amendment["effective_contract_amount"] == 651_713_320
    assert amendment["include_in_family_total"] is True
    assert amendment["relationship_status"] == "confirmed"
    assert amendment["relationship_basis"]["source_contract_family"] == {
        "contract_number": "R25TA00880128",
        "change_order": 1,
        "change_order_raw": "01",
        "evidence_field": "contract_detail_url_query",
        "confirmed_number_matches_contract_number_and_change_order": True,
    }
    assert _contract_family_summary(contracts) == {
        "effective_contract_amount": 651_713_320,
        "effective_contract_event_id": "R25TA0088012801",
        "included_contract_event_ids": ["R25TA0088012801"],
        "latest_confirmed_contract_amount": 651_713_320,
        "latest_confirmed_contract_event_id": "R25TA0088012801",
        "contract_family_count": 1,
        "included_contract_family_count": 1,
        "amount_aggregation_status": "confirmed",
        "amount_aggregation_reason": "confirmed_contract_family_aggregation",
    }


def test_contract_lineage_does_not_sum_unresolved_long_term_series() -> None:
    contracts = []
    rows = (
        (
            "21243090800", "212430908_1", "00", date(2024, 5, 30),
            "퇴직연금 정보시스템 응용프로그램 유지관리 위탁사업", 0,
            1_895_833_330, "2124324646",
        ),
        (
            "R25TA0038107600", "R25TA00381076", "00", date(2025, 4, 4),
            "퇴직연금 정보시스템 응용프로그램 유지관리 위탁사업",
            6_517_833_330, 2_311_000_000, "R25DC00042149",
        ),
        (
            "R25TA0038107601", "R25TA00381076", "01", date(2026, 1, 20),
            "퇴직연금 정보시스템 응용프로그램 유지관리 위탁사업",
            6_914_022_970, 2_499_989_640, "R25DC00042149",
        ),
        (
            "R26TA0166184400", "R26TA01661844", "00", date(2026, 3, 24),
            "퇴직연금 정보시스템 응용프로그램 유지관리 위탁사업(3차)",
            6_914_022_970, 2_518_200_000, "R26DC00186874",
        ),
        (
            "R26TA0166184401", "R26TA01661844", "01", date(2026, 8, 20),
            "퇴직연금 정보시스템 응용프로그램 유지관리 위탁사업(3차)",
            7_359_158_970, 2_963_336_000, "R26DC00186874",
        ),
    )
    for event_id, base_number, order, event_date, name, total, current, request in rows:
        contracts.append({
            "contract_event_id": event_id,
            "first_contract_date": event_date,
            "latest_contract_version_date": event_date,
            "current_contract_amount": current,
            "_lineage_source": {
                "unified_contract_number": f"U-{event_id}",
                "confirmed_contract_number": event_id,
                "contract_reference_number": event_id,
                "contract_name": name,
                "long_term_continuation_type": "장기",
                "total_amount": total,
                "request_number": request,
                "contract_detail_url": (
                    "https://www.g2b.go.kr/link/FIUA027_01/single/"
                    f"?ctrtNo={base_number}&ctrtChgOrd={order}"
                ),
            },
        })

    _decorate_contract_lineage(contracts, bid_notice_id="20240520034:000")

    by_id = {item["contract_event_id"]: item for item in contracts}
    r25 = by_id["R25TA0038107601"]
    r26 = by_id["R26TA0166184401"]
    assert r25["contract_series_id"] == r26["contract_series_id"]
    assert r26["previous_contract_family_id"] == r25["contract_family_id"]
    assert r26["original_contract_family_id"] == by_id["21243090800"][
        "contract_family_id"
    ]
    assert r26["family_relationship_type"] == "continuation"
    assert r26["family_relationship_status"] == "inferred"
    assert r26["family_relationship_basis"][
        "authoritative_series_identifier"
    ] is None
    assert r26["family_relationship_basis"][
        "previous_total_matches_current_entry_total"
    ] is True
    assert _contract_family_summary(contracts) == {
        "effective_contract_amount": None,
        "effective_contract_event_id": None,
        "included_contract_event_ids": [
            "R25TA0038107601", "R26TA0166184401",
        ],
        "latest_confirmed_contract_amount": 7_359_158_970,
        "latest_confirmed_contract_event_id": "R26TA0166184401",
        "contract_family_count": 3,
        "included_contract_family_count": 2,
        "amount_aggregation_status": "unresolved",
        "amount_aggregation_reason": (
            "long_term_continuation_relationship_unresolved"
        ),
    }


def test_contract_time_relationship_excludes_same_day_and_future_contracts() -> None:
    dates = [date(2026, 7, 14), date(2026, 8, 6), date(2026, 8, 6)]
    first = _contract_time_relationship(date(2026, 7, 14), dates)
    later = _contract_time_relationship(date(2026, 8, 6), dates)
    assert first["contract_time_relationship_status"] == "entry_or_reentering"
    assert first["prior_same_organization_field_contract_count"] == 0
    assert later["contract_time_relationship_status"] == "repeat"
    assert later["prior_same_organization_field_contract_count"] == 1
    assert later["history_period_to"] == date(2026, 8, 5)


def test_attention_suppliers_detects_entry_then_repeat() -> None:
    rows = [{"event_key": "ENTRY", "unified_contract_number": "U1",
             "contract_name": "첫 계약", "first_contract_date": date(2026, 7, 14),
             "contract_amount": Decimal("80"), "attributed_contract_amount": Decimal("80"),
             "company_number": "1048188364", "company_name": "웨슬리퀘스트"},
            {"event_key": "REPEAT", "unified_contract_number": "U2",
             "contract_name": "후속 계약", "first_contract_date": date(2026, 8, 6),
             "contract_amount": Decimal("241"), "attributed_contract_amount": Decimal("241"),
             "company_number": "1048188364", "company_name": "웨슬리퀘스트"}]
    result, basis = _build_attention_suppliers(rows,
        history={"1048188364": [date(2026, 7, 14), date(2026, 8, 6)]},
        cutoff=date(2026, 9, 4), period_from=date(2023, 9, 4),
        filters={"work_type": "service", "large_category": "ICT 서비스",
                 "middle_category": "SW 및 시스템 개발", "field_code": "81111599"},
        organization_code="Z004905", reference_amount=Decimal("200"))
    supplier = result[0]
    assert "entry_then_repeat" in supplier["attention_reasons"]
    assert "large_contract_experience" not in supplier["attention_reasons"]
    assert "field_upper_quartile_experience" in supplier["attention_reasons"]
    assert supplier["display_attention_reasons"] == [
        "similar_amount_experience", "contract_amount_leader"]
    assert supplier["attention_reason_evidence"]["entry_then_repeat"]["days_to_repeat"] == 23
    assert supplier["first_contract_status"] == "entry_or_reentering"
    assert basis["selection_method"] == (
        "distinct_reason_representatives_then_quota_fill_and_priority_sort")
    assert basis["sort_priority"][:2] == [
        "similar_amount_experience", "contract_amount_leader"]


@pytest.mark.asyncio
async def test_related_projects_pages_by_contract_event_and_nests_contractors() -> None:
    class Reader:
        def bid_context(self, catalog, **kwargs):
            return ({"notice_name": "현재 사업", "organization_code": "ORG",
                "organization_name": "기관", "notice_published_date": date(2026, 9, 1),
                "work_type": "service", "field_code": "81111599",
                "large_category": "ICT 서비스", "middle_category": "SW 및 시스템 개발",
                "allocated_budget": Decimal("650")}, [])

        def peer_field_contracts(self, catalog, **kwargs):
            base = {"organization_code": "ORG", "organization_name": "기관",
                "work_type": "service", "field_code": "81111599",
                "field_name": "정보시스템개발서비스", "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발", "amount_completeness": "complete",
                "latest_contract_version_date": date(2026, 6, 1), "contract_version_count": 1,
                "normalized_notice_number": None, "company_role": "공동수급", "share_percent": 50}
            return [
                {**base, "event_key": "OLD-A", "unified_contract_number": "OLD-A",
                 "contract_name": "과거 A", "first_contract_date": date(2024, 1, 1),
                 "company_number": "A", "company_name": "A사", "contract_amount": Decimal("100"),
                 "attributed_contract_amount": Decimal("100")},
                {**base, "event_key": "OLD-B", "unified_contract_number": "OLD-B",
                 "contract_name": "과거 B", "first_contract_date": date(2024, 1, 1),
                 "company_number": "B", "company_name": "B사", "contract_amount": Decimal("100"),
                 "attributed_contract_amount": Decimal("100")},
                {**base, "event_key": "JOINT", "unified_contract_number": "JOINT-1",
                 "contract_name": "공동 계약", "first_contract_date": date(2026, 6, 1),
                 "company_number": "A", "company_name": "A사", "contract_amount": Decimal("650"),
                 "attributed_contract_amount": Decimal("331.5")},
                {**base, "event_key": "JOINT", "unified_contract_number": "JOINT-1",
                 "contract_name": "공동 계약", "first_contract_date": date(2026, 6, 1),
                 "company_number": "B", "company_name": "B사", "contract_amount": Decimal("650"),
                 "attributed_contract_amount": Decimal("318.5")},
            ]

    result = await execute_bid_related_projects_search(
        RegistryLoader(REGISTRIES).load(), "search_bid_related_projects",
        {"bid_notice_id": "CURRENT:000", "project_filters": ["repeat_supplier"],
         "page": 1, "page_size": 20}, reader=Reader(),
    )
    joint = next(item for item in result.outcome["items"] if item["contract_event_id"] == "JOINT")
    assert joint["contractor_count"] == 2
    assert joint["relationship_status_summary"] == "repeat"
    assert joint["contractor_amount_completeness"] == "complete"
    assert joint["contractor_attributed_amount_sum"] == 650
    assert result.outcome["pagination"]["total_items"] == 1
    assert result.outcome["filter_counts"]["repeat_supplier"] == 1

    combined = await execute_bid_related_projects_search(
        RegistryLoader(REGISTRIES).load(), "search_bid_related_projects",
        {"bid_notice_id": "CURRENT:000",
         "project_filters": ["similar_amount", "entry_or_reentering_supplier"],
         "filter_operator": "and", "page": 1, "page_size": 20}, reader=Reader(),
    )
    assert combined.outcome["items"] == []
    assert combined.outcome["pagination"]["total_items"] == 0
    assert combined.outcome["applied_filter"] == {
        "filters": ["similar_amount", "entry_or_reentering_supplier"],
        "operator": "and", "total_items": 0,
    }
    assert combined.outcome["filter_counts"] == {
        "all": 3, "similar_amount": 1,
        "entry_or_reentering_supplier": 2, "repeat_supplier": 1,
    }

    either = await execute_bid_related_projects_search(
        RegistryLoader(REGISTRIES).load(), "search_bid_related_projects",
        {"bid_notice_id": "CURRENT:000",
         "project_filters": ["similar_amount", "entry_or_reentering_supplier"],
         "filter_operator": "or", "page": 1, "page_size": 20}, reader=Reader(),
    )
    assert either.outcome["pagination"]["total_items"] == 3
    assert len({item["contract_event_id"] for item in either.outcome["items"]}) == 3

    unfiltered = await execute_bid_related_projects_search(
        RegistryLoader(REGISTRIES).load(), "search_bid_related_projects",
        {"bid_notice_id": "CURRENT:000", "project_filters": [],
         "page": 1, "page_size": 20}, reader=Reader(),
    )
    assert unfiltered.outcome["pagination"]["total_items"] == 3
    assert unfiltered.outcome["applied_filter"]["filters"] == []



class SimilarNoticeReader:
    def find(self, catalog, bid_notice_id, *, period_years, result_statuses):
        assert period_years == 5
        assert result_statuses == ["awarded", "contracted"]
        notice = {
            "bid_notice_id": bid_notice_id,
            "notice_name": "정보시스템 구축 및 유지관리 사업",
            "notice_published_date": date(2026, 9, 1),
            "work_type": "service", "contract_method_name": "일반경쟁",
            "estimated_price": Decimal("200000000"), "allocated_budget": None,
            "demand_organization_code": "ORG-1", "demand_organization_name": "기관",
            "industry_codes": ["1468", "0036"],
            "industries": [
                {"industry_code": "1468", "industry_name": "소프트웨어사업자"},
                {"industry_code": "0036", "industry_name": "정보통신공사업"},
            ],
            "as_of": datetime(2026, 9, 23, tzinfo=timezone.utc),
        }
        rows = [{
            "bid_notice_id": "R25SIMILAR:000", "notice_number": "R25SIMILAR",
            "notice_order": "000", "notice_name": "정보시스템 구축 및 유지관리",
            "notice_published_date": date(2025, 7, 15),
            "work_type": "service", "contract_method_name": "일반경쟁",
            "estimated_price": Decimal("190000000"), "allocated_budget": None,
            "demand_organization_code": "ORG-2", "demand_organization_name": "과거기관",
            "industry_codes": ["1468", "0036"],
            "title_trigram_score": Decimal("0.9"),
            "winner_business_registration_number": "1234567890",
            "winner_name": "스마트이앤씨", "winning_amount": Decimal("170000000"),
            "winning_rate": Decimal("89.5"), "award_date": date(2025, 8, 1),
        }, {
            "bid_notice_id": "R24ORGFIELD:000", "notice_number": "R24ORGFIELD",
            "notice_order": "000", "notice_name": "소득기반 정보시스템 개선 사업",
            "notice_published_date": date(2024, 5, 10),
            "work_type": "service", "contract_method_name": "제한경쟁",
            "estimated_price": Decimal("700000000"), "allocated_budget": None,
            "demand_organization_code": "ORG-1", "demand_organization_name": "기관",
            "industry_codes": ["1468"], "title_trigram_score": Decimal("0.1"),
            "winner_business_registration_number": "9876543210",
            "winner_name": "과거업체", "winning_amount": Decimal("650000000"),
            "winning_rate": Decimal("92.0"), "award_date": date(2024, 6, 1),
        }]
        return notice, rows



class OrganizationFieldEventReader:
    def find(self, catalog, *, organization_code, work_type, as_of):
        return [{
            "source_kind": "award", "notice_number": "R25EVENT",
            "notice_order": "000", "bid_classification_number": "0",
            "rebid_number": "0", "bid_notice_id": "R25EVENT:000",
            "notice_name": "정보시스템 구축", "event_date": date(2025, 3, 1),
            "notice_published_date": date(2025, 2, 20),
            "event_amount": Decimal("200000000"),
            "company_number": "1234567890", "company_name": "기관분야업체",
        }]

    def context(self, catalog, *, organization_code, business_registration_number,
                reference_bid_notice_id):
        return {
            "organization": {
                "organization_code": organization_code, "organization_name": "기관",
            },
            "company": {
                "business_registration_number": business_registration_number,
                "company_name": "기관분야업체",
            },
            "reference_notice": {
                "bid_notice_id": reference_bid_notice_id,
                "notice_name": "정보시스템 구축 및 유지관리 사업",
                "work_type": "service", "estimated_price": Decimal("200000000"),
                "allocated_budget": None, "industry_codes": ["1468", "0036"],
                "as_of": datetime(2026, 9, 23, tzinfo=timezone.utc),
            } if reference_bid_notice_id else None,
        }


@pytest.mark.asyncio
async def test_procurement_outcome_search_merges_awards_contracts_and_paginates() -> None:
    class Reader:
        def find(self, catalog, *, organization_code, period_from, period_to):
            assert organization_code == "ORG-1"
            assert period_from == date(2025, 1, 1)
            assert period_to == date(2026, 1, 1)
            classification = {
                "work_type": "service", "field_code": "81111599",
                "field_name": "정보시스템개발서비스", "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
            }
            awards = [{
                "award_id": "N1:000:0:0", "bid_notice_id": "N1:000",
                "bid_classification_number": "0", "rebid_number": "0",
                "notice_name": "정보시스템 구축", "organization_name": "기관",
                "award_date": date(2025, 3, 1), "winner_name": "낙찰사",
                "winner_business_registration_number": "1111111111",
                "winning_amount": Decimal("90"), "winning_rate": Decimal("87.4"),
                **classification,
            }, {
                "award_id": "N2:000:0:0", "bid_notice_id": "N2:000",
                "bid_classification_number": "0", "rebid_number": "0",
                "notice_name": "정보시스템 운영", "organization_name": "기관",
                "award_date": date(2025, 5, 1), "winner_name": "낙찰전용",
                "winner_business_registration_number": "2222222222",
                "winning_amount": Decimal("80"), "winning_rate": None,
                **classification,
            }]
            contracts = []
            for unified_number, contract_date, amount in (
                ("C1-OLD", date(2024, 4, 1), Decimal("95")),
                ("C1-NEW", date(2025, 4, 1), Decimal("100")),
            ):
                for sequence, number, name, role, share in (
                    (1, "1111111111", "대표사", "주계약업체", Decimal("60")),
                    (2, "3333333333", "구성사", "도급업체", Decimal("40")),
                ):
                    contracts.append({
                        "contract_event_id": "ROOT-C1",
                        "unified_contract_number": unified_number,
                        "bid_notice_id": "N1:000", "notice_name": "정보시스템 구축",
                        "organization_name": "기관", "contract_date": contract_date,
                        "contract_amount": amount, "is_joint_contract": True,
                        "supplier_sequence": sequence,
                        "business_registration_number": number, "supplier_name": name,
                        "supplier_role_name": role, "participation_share_rate": share,
                        **classification,
                    })
            return awards, contracts

    result = await execute_procurement_outcome_search(
        RegistryLoader(REGISTRIES).load(), "search_procurement_outcomes", {
            "organization_code": "ORG-1", "period_from_year": 2025,
            "period_to_year": 2025, "work_type": "service",
            "large_category": "ICT 서비스", "query": "정보시스템",
            "page": 1, "page_size": 20,
        }, reader=Reader(),
    )

    assert result.outcome["pagination"]["total_items"] == 2
    by_id = {item["outcome_id"]: item for item in result.outcome["items"]}
    assert by_id["N1:000"]["stage"] == "contract"
    assert by_id["N1:000"]["latest_activity_date"] == date(2025, 4, 1)
    assert by_id["N1:000"]["contract"]["contract_version_count"] == 2
    assert by_id["N1:000"]["contract"]["contract_amount"] == 100
    assert by_id["N1:000"]["contract"]["lead_contractor"]["company_name"] == "대표사"
    assert by_id["N1:000"]["contract"]["contractor_count"] == 2
    assert len(by_id["N1:000"]["contracts"]) == 1
    assert len(by_id["N1:000"]["awards"]) == 1
    assert by_id["N2:000"]["stage"] == "award"
    assert len(result.objects) == 2


@pytest.mark.asyncio
async def test_procurement_activity_uses_stage_event_period_and_latest_activity_sort() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            classification = {
                "work_type": "service", "field_code": "81111599",
                "field_name": "정보시스템개발서비스", "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
            }
            notices = [{
                "bid_notice_id": "N1:000", "notice_name": "2023년 게시 사업",
                "published_at": datetime(2023, 2, 1, tzinfo=timezone.utc), "bid_begin_at": None,
                "bid_deadline_at": date(2023, 3, 1), "bid_status": "closed",
                "notice_status": "active", "notice_kind_name": "일반공고",
                "organization_code": "ORG-1", "organization_name": "기관",
                **classification,
            }, {
                "bid_notice_id": "N2:000", "notice_name": "예정 사업",
                "published_at": datetime.now(timezone.utc) - timedelta(days=1),
                "bid_begin_at": datetime.now(timezone.utc) + timedelta(days=1),
                "bid_deadline_at": datetime.now(timezone.utc) + timedelta(days=2),
                "bid_status": "scheduled",
                "notice_status": "active", "notice_kind_name": "일반공고",
                "organization_code": "ORG-1", "organization_name": "기관",
                **classification,
            }]
            awards = [{
                "award_id": "N1:000:0:0", "bid_notice_id": "N1:000",
                "bid_classification_number": "0", "rebid_number": "0",
                "award_date": date(2024, 1, 1), "winner_name": "수주사",
                "winner_business_registration_number": "1111111111",
                "winning_amount": Decimal("90"), "winning_rate": None,
            }]
            contracts = [{
                "contract_event_id": "ROOT-1", "unified_contract_number": "C1",
                "bid_notice_id": "N1:000", "notice_name": "2023년 게시 사업",
                "organization_name": "기관", "contract_date": date(2025, 5, 1),
                "contract_amount": Decimal("100"), "is_joint_contract": False,
                "supplier_sequence": 1, "business_registration_number": "1111111111",
                "supplier_name": "수주사", "supplier_role_name": "주계약업체",
                "participation_share_rate": Decimal("100"), **classification,
            }, {
                "contract_event_id": "ROOT-2", "unified_contract_number": "C2",
                "bid_notice_id": None, "notice_name": "독립 계약",
                "organization_name": "기관", "contract_date": date(2024, 6, 1),
                "contract_amount": Decimal("50"), "is_joint_contract": False,
                "supplier_sequence": 1, "business_registration_number": "2222222222",
                "supplier_name": "계약사", "supplier_role_name": "주계약업체",
                "participation_share_rate": Decimal("100"), **classification,
            }]
            return notices, awards, contracts, set()

    catalog = RegistryLoader(REGISTRIES).load()
    first = await execute_procurement_activity_search(
        catalog, "search_procurement_activity", {
            "organization_code": "ORG-1", "period_from_year": 2023,
            "period_to_year": 2026, "stage": "all", "page": 1, "page_size": 2,
        }, reader=Reader(),
    )
    second = await execute_procurement_activity_search(
        catalog, "search_procurement_activity", {
            "organization_code": "ORG-1", "period_from_year": 2023,
            "period_to_year": 2026, "stage": "all", "page": 2, "page_size": 2,
        }, reader=Reader(),
    )

    assert first.outcome["pagination"] == {
        "page": 1, "page_size": 2, "total_items": 3, "total_pages": 2,
    }
    assert second.outcome["pagination"]["total_items"] == 3
    assert first.outcome["stage_counts"] == second.outcome["stage_counts"]
    assert first.outcome["stage_counts"]["all"] == 3
    assert first.outcome["linkage_counts"] == {"linked": 2, "unlinked": 1}
    assert sum(first.outcome["stage_counts"][key] for key in (
        "scheduled", "open", "closed", "award", "contract", "failed", "cancelled",
    )) == 3
    assert first.outcome["items"][0]["activity_id"] == "N2:000"
    assert first.outcome["items"][0]["stage"] == "open"
    assert first.outcome["items"][1]["activity_id"] == "contract:ROOT-1"
    assert first.outcome["items"][1]["stage"] == "contract"
    assert first.outcome["items"][1]["notice"]["published_at"] == datetime(
        2023, 2, 1, tzinfo=timezone.utc,
    )
    assert first.outcome["items"][1]["latest_activity_date"] == date(2025, 5, 1)
    assert second.outcome["items"][0]["notice_linkage"] == "unlinked"
    assert first.outcome["analysis_basis"]["period_basis"] == "stage_event_date"
    assert first.outcome["analysis_basis"]["notice_stage_period_basis"] == (
        "notice_published_at"
    )
    assert first.outcome["analysis_basis"]["award_stage_period_basis"] == (
        "final_award_date_or_opening_at"
    )
    assert first.outcome["analysis_basis"]["contract_stage_period_basis"] == (
        "first_contract_date"
    )
    assert first.outcome["analysis_basis"]["bid_begin_at_used_for_stage"] is False


@pytest.mark.asyncio
async def test_procurement_activity_separates_source_confirmed_failure_and_cancellation() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            del catalog, kwargs
            common = {
                "published_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "bid_begin_at": None, "bid_deadline_at": date(2026, 1, 2),
                "bid_status": "closed", "notice_status": "active",
                "notice_kind_name": "등록공고", "organization_code": "ORG-1",
                "organization_name": "기관", "work_type": "service",
                "field_code": None, "field_name": None, "large_category": None,
                "middle_category": None,
            }
            return [
                {
                    **common, "bid_notice_id": "FAILED:000", "notice_name": "유찰 사업",
                    "current_status": "failed", "current_status_label": "유찰",
                    "failure_reason": "단독입찰", "failure_at": datetime(
                        2026, 1, 2, tzinfo=timezone.utc,
                    ),
                    "status_source": "pps_bid_result_api.list_failing_opening_results",
                },
                {
                    **common, "bid_notice_id": "CANCELLED:001", "notice_name": "취소 사업",
                    "notice_status": "cancelled", "current_status": "cancelled",
                    "current_status_label": "취소", "cancellation_reason": "사업계획 변경",
                    "cancellation_at": datetime(2026, 1, 3, tzinfo=timezone.utc),
                    "status_source": "pps_bid_notice_api.notice_kind_name",
                },
            ], [], [], set()

    result = await execute_procurement_activity_search(
        RegistryLoader(REGISTRIES).load(), "search_procurement_activity", {
            "organization_code": "ORG-1", "period_from_year": 2026,
            "period_to_year": 2026, "stage": "all", "view_mode": "notice_grouped",
            "page": 1, "page_size": 20,
        }, reader=Reader(),
    )

    assert result.outcome["stage_counts"]["failed"] == 1
    assert result.outcome["stage_counts"]["cancelled"] == 1
    assert result.outcome["stage_counts"]["all"] == 2
    by_stage = {item["latest_stage"]: item for item in result.outcome["items"]}
    assert by_stage["failed"]["notice"]["failure_reason"] == "단독입찰"
    assert by_stage["cancelled"]["notice"]["cancellation_reason"] == "사업계획 변경"


@pytest.mark.asyncio
async def test_procurement_activity_returns_one_contract_record_per_contract_event() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            classification = {
                "work_type": "service", "field_code": "81111599",
                "field_name": "정보시스템개발서비스", "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
            }
            contracts = []
            for event_id, unified_number, first_date, latest_date, amount in (
                ("EVENT-1", "C1-V2", date(2024, 2, 1), date(2024, 11, 1), 130),
                ("EVENT-2", "C2", date(2024, 7, 1), date(2024, 7, 1), 80),
            ):
                contracts.append({
                    "contract_event_id": event_id,
                    "unified_contract_number": unified_number,
                    "bid_notice_id": "OLD:000",
                    "notice_name": "기간 이전 게시 공고의 계약",
                    "organization_name": "기관",
                    "first_contract_date": first_date,
                    "contract_date": latest_date,
                    "contract_amount": Decimal(amount),
                    "contract_version_count": 2 if event_id == "EVENT-1" else 1,
                    "is_joint_contract": False, "supplier_sequence": 1,
                    "business_registration_number": "1111111111",
                    "supplier_name": "계약사", "supplier_role_name": "주계약업체",
                    "participation_share_rate": Decimal("100"), **classification,
                })
            return [], [], contracts, set()

    result = await execute_procurement_activity_search(
        RegistryLoader(REGISTRIES).load(), "search_procurement_activity", {
            "organization_code": "ORG-1", "period_from_year": 2024,
            "period_to_year": 2024, "stage": "contract", "page": 1,
            "page_size": 20,
        }, reader=Reader(),
    )

    assert result.outcome["pagination"]["total_items"] == 2
    assert result.outcome["stage_counts"]["contract"] == 2
    assert {item["activity_id"] for item in result.outcome["items"]} == {
        "contract:EVENT-1", "contract:EVENT-2",
    }
    by_id = {item["activity_id"]: item for item in result.outcome["items"]}
    assert by_id["contract:EVENT-1"]["latest_activity_date"] == date(2024, 2, 1)
    assert by_id["contract:EVENT-1"]["contract"]["contract_date"] == date(2024, 11, 1)
    assert by_id["contract:EVENT-1"]["contract"]["contract_version_count"] == 2
    assert by_id["contract:EVENT-1"]["notice_linkage"] == "linked"
    assert result.outcome["analysis_basis"]["deduplication"]["contract"] == (
        "merged_by_contract_event"
    )


@pytest.mark.asyncio
async def test_procurement_activity_notice_grouped_groups_before_pagination() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            classification = {
                "work_type": "service", "field_code": "81111599",
                "field_name": "정보시스템개발서비스", "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
            }
            common_notice = {
                "published_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "bid_begin_at": None, "bid_deadline_at": date(2024, 1, 31),
                "bid_status": "closed", "notice_status": "active",
                "notice_kind_name": "일반공고", "organization_code": "ORG-1",
                "organization_name": "기관", "allocated_budget": None,
                "estimated_price": Decimal("600"), "base_amount": Decimal("500"),
                **classification,
            }
            notices = [{
                **common_notice, "bid_notice_id": "N1:000",
                "notice_name": "같은 이름의 사업",
            }, {
                **common_notice, "bid_notice_id": "N2:000",
                "notice_name": "같은 이름의 사업",
            }]
            awards = [{
                "award_id": "A1", "bid_notice_id": "N1:000",
                "bid_classification_number": "0", "rebid_number": "0",
                "award_date": date(2024, 2, 1), "winner_name": "낙찰사",
                "winner_business_registration_number": "1111111111",
                "winning_amount": Decimal("90"), "winning_rate": None,
            }]
            contracts = [{
                "contract_event_id": "EVENT-1", "unified_contract_number": "C1-V2",
                "confirmed_contract_number": "SOURCE-1",
                "contract_reference_number": "SOURCE-1",
                "contract_name": "같은 이름의 사업(1차)",
                "long_term_continuation_type": "장기", "total_amount": Decimal("1000"),
                "total_amount_currency": "KRW",
                "current_contract_amount_currency": "KRW",
                "bid_notice_id": "N1:000", "notice_name": "같은 이름의 사업",
                "organization_name": "기관", "first_contract_date": date(2024, 3, 1),
                "contract_date": date(2024, 10, 1), "contract_amount": Decimal("0"),
                "contract_version_count": 2, "is_joint_contract": False,
                "supplier_sequence": 1, "business_registration_number": "1111111111",
                "supplier_name": "첫째계약사", "supplier_role_name": "주계약업체",
                "participation_share_rate": Decimal("100"), **classification,
            }, {
                "contract_event_id": "EVENT-2", "unified_contract_number": "C2",
                "confirmed_contract_number": "SOURCE-2",
                "contract_reference_number": "SOURCE-2",
                "contract_name": "같은 이름의 사업(2차)",
                "long_term_continuation_type": "장기", "total_amount": Decimal("1000"),
                "total_amount_currency": "KRW",
                "current_contract_amount_currency": "KRW",
                "bid_notice_id": "N1:000", "notice_name": "같은 이름의 사업",
                "organization_name": "기관", "first_contract_date": date(2024, 8, 1),
                "contract_date": date(2024, 8, 1), "contract_amount": None,
                "contract_version_count": 1, "is_joint_contract": False,
                "supplier_sequence": 1, "business_registration_number": "2222222222",
                "supplier_name": "둘째계약사", "supplier_role_name": "주계약업체",
                "participation_share_rate": Decimal("100"), **classification,
            }, {
                "contract_event_id": "EVENT-3", "unified_contract_number": "C3",
                "confirmed_contract_number": "SOURCE-3",
                "contract_reference_number": "SOURCE-3",
                "contract_name": "미연결 계약",
                "long_term_continuation_type": "신규", "total_amount": Decimal("70"),
                "total_amount_currency": "KRW",
                "current_contract_amount_currency": "KRW",
                "bid_notice_id": None, "notice_name": "미연결 계약",
                "organization_name": "기관", "first_contract_date": date(2024, 7, 1),
                "contract_date": date(2024, 7, 1), "contract_amount": Decimal("70"),
                "contract_version_count": 1, "is_joint_contract": False,
                "supplier_sequence": 1, "business_registration_number": "3333333333",
                "supplier_name": "독립계약사", "supplier_role_name": "주계약업체",
                "participation_share_rate": Decimal("100"), **classification,
            }]
            return notices, awards, contracts, set()

    catalog = RegistryLoader(REGISTRIES).load()
    common_inputs = {
        "organization_code": "ORG-1", "period_from_year": 2024,
        "period_to_year": 2024, "stage": "all", "view_mode": "notice_grouped",
        "page_size": 1,
    }
    first = await execute_procurement_activity_search(
        catalog, "search_procurement_activity", {**common_inputs, "page": 1},
        reader=Reader(),
    )
    second = await execute_procurement_activity_search(
        catalog, "search_procurement_activity", {**common_inputs, "page": 2},
        reader=Reader(),
    )
    all_groups = await execute_procurement_activity_search(
        catalog, "search_procurement_activity", {
            **common_inputs, "page": 1, "page_size": 20,
        }, reader=Reader(),
    )

    assert first.outcome["pagination"] == {
        "page": 1, "page_size": 1, "total_items": 3, "total_pages": 3,
    }
    assert first.outcome["stage_counts"] == {
        "scheduled": 0, "open": 0, "closed": 1, "award": 0,
        "contract": 2, "failed": 0, "cancelled": 0, "all": 3,
    }
    assert sum(
        first.outcome["stage_counts"][stage]
        for stage in ("scheduled", "open", "closed", "award", "contract",
                      "failed", "cancelled")
    ) == first.outcome["stage_counts"]["all"]
    assert first.outcome["items"][0]["activity_group_id"] == "notice:N1:000"
    assert second.outcome["items"][0]["activity_group_id"] == "contract:EVENT-3"
    assert (
        first.outcome["items"][0]["activity_group_id"]
        != second.outcome["items"][0]["activity_group_id"]
    )
    assert {
        item["activity_group_id"] for item in all_groups.outcome["items"]
    } == {"notice:N1:000", "notice:N2:000", "contract:EVENT-3"}
    independent = next(
        item for item in all_groups.outcome["items"]
        if item["activity_group_id"] == "contract:EVENT-3"
    )["contracts"][0]
    assert independent["contract_family_id"] == "contract-family:EVENT-3"
    assert independent["contract_structure"] == "single"
    assert independent["contract_record_type"] == "independent"
    assert independent["relationship_status"] == "confirmed"
    assert independent["relationship_basis"]["contract_event_identity"] == {
        "field": "confirmed_contract_number", "value": "SOURCE-3",
    }
    group = first.outcome["items"][0]
    assert group["latest_stage"] == "contract"
    assert group["notice"] == {
        "notice_name": "같은 이름의 사업",
        "published_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "bid_begin_at": None, "deadline_at": date(2024, 1, 31),
        "status": "closed", "notice_status": "active", "work_type": "service",
        "current_status": None, "current_status_label": None,
        "cancellation_reason": None, "cancellation_at": None,
        "failure_reason": None, "failure_at": None,
        "status_source": None, "status_confirmed_at": None,
        "original_notice_id": None, "current_notice_id": None,
        "revision_number": None, "is_latest_revision": None,
        "project_amount": 600, "project_amount_basis": "estimated_price",
        "project_amount_basis_name": "추정가격",
    }
    assert group["result_summary"] == {
        "award_count": 1, "contract_event_count": 2,
        "contract_version_count": 3,
        "effective_contract_amount": 1000,
        "effective_contract_event_id": "EVENT-2",
        "included_contract_event_ids": ["EVENT-2"],
        "latest_confirmed_contract_amount": None,
        "latest_confirmed_contract_event_id": None,
        "contract_family_count": 1,
        "included_contract_family_count": 1,
        "amount_aggregation_status": "partially_confirmed",
        "amount_aggregation_reason": "inferred_contract_family_relationship",
    }
    by_contract = {
        item["contract_event_id"]: item for item in group["contracts"]
    }
    assert by_contract["EVENT-1"]["first_contract_date"] == date(2024, 3, 1)
    assert by_contract["EVENT-1"]["latest_contract_version_date"] == date(
        2024, 10, 1,
    )
    assert by_contract["EVENT-1"]["current_contract_amount"] == 0
    assert by_contract["EVENT-1"]["contract_version_count"] == 2
    assert by_contract["EVENT-2"]["current_contract_amount"] is None
    assert by_contract["EVENT-1"]["contract_structure"] == "long_term_continuing"
    assert by_contract["EVENT-1"]["contract_record_type"] == "original"
    assert by_contract["EVENT-1"]["phase_number"] == 1
    assert by_contract["EVENT-1"]["parent_contract_event_id"] is None
    assert by_contract["EVENT-1"]["original_contract_event_id"] == "EVENT-1"
    assert by_contract["EVENT-1"]["total_contract_amount"] == 1000
    assert by_contract["EVENT-1"]["phase_contract_amount"] == 0
    assert by_contract["EVENT-1"]["amount_tax_basis"] == "unknown"
    assert by_contract["EVENT-1"]["relationship_status"] == "inferred"
    assert by_contract["EVENT-2"]["contract_family_id"] == (
        by_contract["EVENT-1"]["contract_family_id"]
    )
    assert by_contract["EVENT-2"]["contract_record_type"] == "phase"
    assert by_contract["EVENT-2"]["phase_number"] == 2
    assert by_contract["EVENT-2"]["parent_contract_event_id"] == "EVENT-1"
    assert by_contract["EVENT-2"]["original_contract_event_id"] == "EVENT-1"
    assert by_contract["EVENT-2"]["relationship_status"] == "inferred"
    assert by_contract["EVENT-2"]["relationship_basis"]["family_inference"] == {
        "bid_notice_id": "N1:000",
        "long_term_continuation_type": "장기",
        "normalized_contract_name": "같은 이름의 사업",
        "phase_marker": 2,
        "parent_link_basis": "same_inferred_family_with_phase_marker",
    }
    assert first.outcome["grouping_basis"]["linked_group_key"] == "bid_notice_id"
    assert first.outcome["analysis_basis"]["view_mode"] == "notice_grouped"

    flat = await execute_procurement_activity_search(
        catalog, "search_procurement_activity", {
            "organization_code": "ORG-1", "period_from_year": 2024,
            "period_to_year": 2024, "stage": "all", "page": 1, "page_size": 20,
        }, reader=Reader(),
    )
    assert flat.outcome["pagination"]["total_items"] == 4
    assert "grouping_basis" not in flat.outcome
    assert flat.outcome["analysis_basis"]["view_mode"] == "flat"
    assert all(
        "_lineage_source" not in contract
        for item in flat.outcome["items"]
        for contract in item["contracts"]
    )


@pytest.mark.asyncio
async def test_procurement_activity_contract_filter_uses_profile_field_identity() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            notices = [{
                "bid_notice_id": "N1:000", "notice_name": "연결 공고",
                "published_at": date(2024, 1, 1), "bid_begin_at": None,
                "bid_deadline_at": date(2024, 1, 31), "bid_status": "closed",
                "notice_status": "active", "organization_name": "기관",
                "work_type": "service", "field_code": "NOTICE-FIELD",
                "field_name": "일반용역", "large_category": "일반용역",
                "middle_category": None,
            }]
            contracts = [{
                "contract_event_id": "EVENT-1", "unified_contract_number": "C1",
                "bid_notice_id": "N1:000", "notice_name": "연결 공고",
                "organization_name": "기관", "first_contract_date": date(2024, 2, 1),
                "contract_date": date(2024, 2, 1), "contract_amount": Decimal("100"),
                "contract_version_count": 1, "is_joint_contract": False,
                "supplier_sequence": 1, "business_registration_number": "1111111111",
                "supplier_name": "계약사", "supplier_role_name": "주계약업체",
                "participation_share_rate": Decimal("100"), "work_type": "service",
                "procurement_classification_number": "TECH-1",
                "procurement_classification_name": "엔지니어링서비스",
                "procurement_large_classification_name": "기술용역",
                "procurement_middle_classification_name": "설계용역",
                "purchase_items": [],
            }]
            return notices, [], contracts, set()

    result = await execute_procurement_activity_search(
        RegistryLoader(REGISTRIES).load(), "search_procurement_activity", {
            "organization_code": "ORG-1", "period_from_year": 2024,
            "period_to_year": 2024, "stage": "contract", "work_type": "service",
            "large_category": "기술용역", "page": 1, "page_size": 20,
        }, reader=Reader(),
    )

    assert result.outcome["pagination"]["total_items"] == 1
    assert result.outcome["items"][0]["field_code"] == "TECH-1"
    assert result.outcome["items"][0]["large_category"] == "기술용역"


@pytest.mark.asyncio
async def test_procurement_activity_selects_display_project_amount_by_source_priority() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            common = {
                "published_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                "bid_begin_at": None, "bid_deadline_at": date(2025, 1, 31),
                "bid_status": "closed", "notice_status": "active",
                "notice_kind_name": "일반공고", "organization_code": "ORG-1",
                "organization_name": "기관", "work_type": "service",
                "field_code": None, "field_name": None, "large_category": None,
                "middle_category": None,
            }
            notices = [{
                **common, "bid_notice_id": "BUDGET:000", "notice_name": "예산 공고",
                "allocated_budget": Decimal("120"),
                "estimated_price": Decimal("110"), "base_amount": Decimal("100"),
            }, {
                **common, "bid_notice_id": "ESTIMATED:000", "notice_name": "추정가격 공고",
                "allocated_budget": None, "estimated_price": Decimal("210"),
                "base_amount": Decimal("200"),
            }, {
                **common, "bid_notice_id": "BASE:000", "notice_name": "기초금액 공고",
                "allocated_budget": None, "estimated_price": None,
                "base_amount": Decimal("300"),
            }, {
                **common, "bid_notice_id": "EMPTY:000", "notice_name": "금액 없는 공고",
                "allocated_budget": None, "estimated_price": None, "base_amount": None,
            }]
            contracts = [{
                "contract_event_id": "ROOT-1", "unified_contract_number": "C1",
                "bid_notice_id": None, "notice_name": "독립 계약",
                "organization_name": "기관", "contract_date": date(2025, 2, 1),
                "contract_amount": Decimal("400"), "is_joint_contract": False,
                "supplier_sequence": 1, "business_registration_number": "1111111111",
                "supplier_name": "계약사", "supplier_role_name": "주계약업체",
                "participation_share_rate": Decimal("100"), "work_type": "service",
                "field_code": None, "field_name": None, "large_category": None,
                "middle_category": None,
            }]
            return notices, [], contracts, set()

    result = await execute_procurement_activity_search(
        RegistryLoader(REGISTRIES).load(), "search_procurement_activity", {
            "organization_code": "ORG-1", "period_from_year": 2025,
            "period_to_year": 2025, "page": 1, "page_size": 20,
        }, reader=Reader(),
    )

    by_id = {item["activity_id"]: item for item in result.outcome["items"]}
    assert (
        by_id["BUDGET:000"]["project_amount"],
        by_id["BUDGET:000"]["project_amount_basis"],
        by_id["BUDGET:000"]["project_amount_basis_name"],
    ) == (120, "allocated_budget", "배정예산")
    assert by_id["BUDGET:000"]["notice"]["estimated_price"] == 110
    assert by_id["ESTIMATED:000"]["project_amount"] == 210
    assert by_id["ESTIMATED:000"]["project_amount_basis"] == "estimated_price"
    assert by_id["BASE:000"]["project_amount"] == 300
    assert by_id["BASE:000"]["project_amount_basis"] == "base_amount"
    assert by_id["EMPTY:000"]["project_amount"] is None
    assert by_id["EMPTY:000"]["project_amount_basis"] is None
    assert by_id["contract:ROOT-1"]["project_amount"] == 400
    assert by_id["contract:ROOT-1"]["project_amount_basis"] == "contract_amount"
    assert by_id["contract:ROOT-1"]["project_amount_basis_name"] == "계약금액"


@pytest.mark.asyncio
async def test_contract_search_enrichment_returns_lead_members_and_share_completeness() -> None:
    class Reader:
        def find(self, catalog, *, unified_contract_numbers):
            assert unified_contract_numbers == ["C-1"]
            return [
                {
                    "unified_contract_number": "C-1", "is_joint_contract": True,
                    "supplier_sequence": 2, "business_registration_number": "1078700904",
                    "supplier_name": "한국이디에스", "supplier_role_name": "주계약업체",
                    "joint_contract_method_name": "공동",
                    "participation_share_rate": Decimal("60"),
                },
                {
                    "unified_contract_number": "C-1", "is_joint_contract": True,
                    "supplier_sequence": 1, "business_registration_number": "1234567890",
                    "supplier_name": "구성업체", "supplier_role_name": "도급업체",
                    "joint_contract_method_name": "공동", "participation_share_rate": None,
                },
            ]

    contract = MaterializedObject(
        ontology="public_procurement", object_type="contract", object_id="contract-id",
        properties={"unified_contract_number": "C-1", "is_joint_contract": True},
        provenance=[], property_provenance={},
    )
    await enrich_contract_search_objects(
        RegistryLoader(REGISTRIES).load(), [contract],
        observed_at=datetime(2026, 10, 1, tzinfo=timezone.utc), reader=Reader(),
    )

    assert contract.properties["contractor_count"] == 2
    assert contract.properties["lead_contractor"]["company_name"] == "한국이디에스"
    assert contract.properties["contractors"][0]["company_role"] == "consortium_lead"
    assert contract.properties["contractors"][0]["share_percent"] == 60
    assert contract.properties["contractors"][0]["share_completeness"] == "complete"
    assert contract.properties["contractors"][1]["company_role"] == "consortium_member"
    assert contract.properties["contractors"][1]["share_percent"] is None
    assert contract.properties["contractors"][1]["share_completeness"] == "unknown"
    assert contract.property_provenance["contractors"][0].operation == "contract_suppliers"



def test_industry_license_status_distinguishes_absence_incomplete_and_source_failure() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    notice = {
        "bid_notice_id": "R26TEST:000",
        "requirement_expression": None,
        "extraction_completeness": "complete",
    }
    assert _industry_license_eligibility(
        notice, [], {"industries": [], "industries_available": True}, date(2026, 9, 22), catalog,
    )["status"] == "not_applicable"
    assert _industry_license_eligibility(
        {**notice, "extraction_completeness": "partial"}, [],
        {"industries": [], "industries_available": True}, date(2026, 9, 22), catalog,
    )["status"] == "needs_review"
    requirement = {
        "requirement_id": "req-1", "bid_notice_id": "R26TEST:000", "local_id": "r1",
        "requirement_type": "industry_license", "value_text": '{"text":"소프트웨어사업자"}',
        "original_text": "소프트웨어사업자 등록", "mandatory": True,
        "assessment_stage": "bid_entry", "standard_rule_id": "has_registered_industry",
        "standard_rule_version": "1.0.0", "rule_arguments_text": '{"expected_value":"1468"}',
    }
    result = _industry_license_eligibility(
        notice, [requirement], {"industries": [], "industries_available": False},
        date(2026, 9, 22), catalog,
    )
    assert result["status"] == "unknown"
    assert result["reason_codes"] == ["source_unavailable"]



@pytest.mark.asyncio
async def test_organization_company_field_relationship_returns_event_distributions() -> None:
    result = await execute_organization_company_field_relationship(
        RegistryLoader(REGISTRIES).load(),
        "get_organization_company_field_relationship",
        {
            "organization_code": "ORG-1",
            "business_registration_number": "1234567890",
            "field_code": "information_system",
            "work_type": "service",
            "reference_bid_notice_id": "R26TEST:000",
            "period_years": 10,
            "page": 1,
            "page_size": 20,
        },
        reader=OrganizationFieldEventReader(),
    )

    assert result.outcome["summary"]["award_event_count"] == 1
    assert result.outcome["summary"]["attributed_award_event_count"] == 1
    assert sum(item["event_count"] for item in result.outcome["project_type_distribution"]) == 1
    assert sum(item["event_count"] for item in result.outcome["amount_distribution"]) == 1
    assert sum(item["event_count"] for item in result.outcome["yearly_activity"]) == 1
    assert result.outcome["events"][0]["is_similar_amount"] is True
    assert result.outcome["events"][0]["notice_published_date"] == date(2025, 2, 20)
    assert result.outcome["events"][0]["award_date"] == date(2025, 3, 1)
    assert result.outcome["events"][0]["contract_date"] is None
    assert result.outcome["events"][0]["attributed_contract_amount_completeness"] == "unknown"
    assert result.outcome["events"][0]["company_role"] == "sole"
    assert result.outcome["summary"]["total_attributed_contract_amount"] == 0
    assert result.outcome["summary"]["amount_completeness"] == "unknown"
    assert result.outcome["pagination"]["total_items"] == 1


@pytest.mark.asyncio
async def test_organization_company_relationship_does_not_apply_field_filter() -> None:
    result = await execute_organization_company_relationship(
        RegistryLoader(REGISTRIES).load(),
        "get_organization_company_relationship",
        {
            "organization_code": "ORG-1",
            "business_registration_number": "1234567890",
            "work_type": "service",
            "period_years": 10,
            "page": 1,
            "page_size": 20,
        },
        reader=OrganizationFieldEventReader(),
    )

    assert result.outcome["relationship_type"] == "organization_history"
    assert result.outcome["analysis_basis"]["field_filter_applied"] is False
    assert result.outcome["analysis_basis"]["similarity_assessment_applied"] is False
    assert result.outcome["events"][0]["organization_match"] is True
    assert "field_match_reasons" not in result.outcome["events"][0]
    assert result.objects[0].object_type == "organization_company_relationship"


@pytest.mark.asyncio
async def test_organization_company_relationship_applies_procurement_hierarchy_filters() -> None:
    class Reader(OrganizationFieldEventReader):
        received = None

        def find(self, catalog, **kwargs):
            self.received = kwargs
            return super().find(
                catalog,
                organization_code=kwargs["organization_code"],
                work_type=kwargs["work_type"],
                as_of=kwargs["as_of"],
            )

    reader = Reader()
    result = await execute_organization_company_relationship(
        RegistryLoader(REGISTRIES).load(), "get_organization_company_relationship",
        {
            "organization_code": "ORG-1",
            "business_registration_number": "1234567890",
            "work_type": "service",
            "large_category": "ICT 서비스",
            "middle_category": "SW 및 시스템 개발",
            "field_code": "81111599",
            "period_years": 10,
            "page": 1,
            "page_size": 20,
        },
        reader=reader,
    )

    assert reader.received["large_category"] == "ICT 서비스"
    assert reader.received["middle_category"] == "SW 및 시스템 개발"
    assert reader.received["procurement_field_code"] == "81111599"
    assert result.outcome["analysis_basis"]["field_filter_applied"] is True
    assert result.outcome["analysis_basis"]["field_filter"] == {
        "large_category": "ICT 서비스",
        "middle_category": "SW 및 시스템 개발",
        "field_code": "81111599",
    }


@pytest.mark.asyncio
async def test_organization_company_relationship_limits_metrics_and_separates_versions() -> None:
    class Reader(OrganizationFieldEventReader):
        def find(self, catalog, *, organization_code, work_type, as_of):
            rows = []
            for contract_number, event_date, amount in (
                ("C-OLD", date(2021, 5, 1), Decimal("80")),
                ("C-V1", date(2023, 5, 1), Decimal("90")),
                ("C-V2", date(2025, 5, 1), Decimal("100")),
            ):
                rows.append({
                    "source_kind": "contract", "notice_number": "N1",
                    "unified_contract_number": contract_number,
                    "original_contract_number": contract_number,
                    "bid_notice_id": "N1:000", "notice_name": "정보시스템 유지관리",
                    "event_date": event_date, "event_amount": amount,
                    "notice_published_date": date(2023, 2, 1),
                    "attribution_date": date(2023, 2, 1),
                    "attribution_date_basis": "notice_published_at",
                    "first_contract_date": date(2021, 5, 1),
                    "latest_contract_version_date": date(2025, 5, 1),
                    "contract_amount": amount, "contract_currency": "KRW",
                    "company_number": "1234567890", "company_name": "기관분야업체",
                    "participation_share_rate": Decimal("100"),
                    "supplier_role_name": "단독",
                })
            return rows

    result = await execute_organization_company_relationship(
        RegistryLoader(REGISTRIES).load(), "get_organization_company_relationship",
        {
            "organization_code": "ORG-1", "business_registration_number": "1234567890",
            "period_years": 5, "page": 1, "page_size": 20,
        }, reader=Reader(),
    )

    summary = result.outcome["summary"]
    assert summary["unique_project_count"] == 1
    assert summary["contract_event_count"] == 1
    assert summary["contract_version_count"] == 3
    assert summary["total_attributed_contract_amount"] == 100
    assert summary["active_years"] == [2023]
    assert result.outcome["yearly_activity"] == [{
        "year": 2023, "award_event_count": 1,
        "attributed_contract_amount": 100, "amount_completeness": "complete",
        "sole_count": 1, "consortium_lead_count": 0, "consortium_member_count": 0,
    }]
    assert result.outcome["events"][0]["first_contract_date"] == date(2021, 5, 1)
    assert result.outcome["events"][0]["latest_contract_version_date"] == date(2025, 5, 1)


@pytest.mark.asyncio
async def test_organization_company_relationship_validates_explicit_year_range() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    base = {
        "organization_code": "ORG-1",
        "business_registration_number": "1234567890",
    }
    with pytest.raises(CapabilityExecutionError, match="must be provided together"):
        await execute_organization_company_relationship(
            catalog, "get_organization_company_relationship",
            {**base, "period_from_year": 2023},
        )
    with pytest.raises(CapabilityExecutionError, match="less than or equal"):
        await execute_organization_company_relationship(
            catalog, "get_organization_company_relationship",
            {**base, "period_from_year": 2025, "period_to_year": 2023},
        )
    with pytest.raises(CapabilityExecutionError, match="cannot be later"):
        await execute_organization_company_relationship(
            catalog, "get_organization_company_relationship",
            {**base, "period_from_year": 2026, "period_to_year": 2027},
        )


@pytest.mark.asyncio
async def test_company_similar_project_experience_uses_any_industry_overlap() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            return ({
                "notice_name": "정보시스템 구축 및 운영 사업",
                "work_type": "service",
                "estimated_price": Decimal("200000000"),
                "allocated_budget": None,
                "industry_codes": ["0036", "1468"],
                "industry_names": {"0036": "정보통신공사업", "1468": "소프트웨어사업자"},
            }, [{
                "bid_notice_id": "R25ONE:000",
                "notice_name": "전산장비 운영 용역",
                "notice_published_date": date(2025, 1, 1),
                "demand_organization_code": "ORG-2",
                "demand_organization_name": "다른기관",
                "work_type": "service",
                "estimated_price": Decimal("180000000"),
                "allocated_budget": None,
                "industry_codes": ["1468"],
                "award_date": date(2025, 2, 1),
                "winning_amount": Decimal("170000000"),
                "contract_date": None,
                "contract_amount": None,
                "participation_share_rate": None,
                "supplier_role_name": None,
                "supplier_count": 0,
            }])

    result = await execute_company_similar_project_experience(
        RegistryLoader(REGISTRIES).load(),
        "get_company_similar_project_experience",
        {
            "reference_bid_notice_id": "R26TEST:000",
            "business_registration_number": "1234567890",
            "period_years": 10,
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )

    assessment = result.outcome["experiences"][0]["industry_license_assessment"]
    assert assessment["matched_codes"] == ["1468"]
    assert assessment["coverage_ratio"] == 0.5
    assert assessment["all_required_codes_included"] is False
    assert result.outcome["analysis_basis"]["title_keyword_filter_applied"] is False
    assert result.outcome["summary"]["candidate_count"] == 1
    assert result.outcome["summary"]["event_count"] == 1
    assert result.outcome["summary"]["limited_event_count"] == 1
    assert result.objects[0].object_type == "company_similar_project_experience"


def test_award_event_analysis_merges_contract_and_preserves_joint_members() -> None:
    rows = [{
        "source_kind": "award", "notice_number": "R25A", "notice_order": "000",
        "bid_classification_number": "0", "rebid_number": "0",
        "bid_notice_id": "R25A:000", "notice_name": "정보시스템 구축",
        "event_date": date(2025, 3, 1), "event_amount": Decimal("200000000"),
        "company_number": "1111111111", "company_name": "대표사",
    }, {
        "source_kind": "contract", "notice_number": "R25A",
        "unified_contract_number": "C1-1", "original_contract_number": "C1",
        "bid_notice_id": "R25A:000", "notice_name": "정보시스템 구축",
        "event_date": date(2025, 3, 10), "event_amount": Decimal("200000000"),
        "contract_amount": Decimal("200000000"), "contract_currency": "KRW",
        "company_number": "1111111111", "company_name": "대표사",
        "participation_share_rate": Decimal("60"), "supplier_role_name": "대표사",
    }, {
        "source_kind": "contract", "notice_number": "R25A",
        "unified_contract_number": "C1-1", "original_contract_number": "C1",
        "bid_notice_id": "R25A:000", "notice_name": "정보시스템 구축",
        "event_date": date(2025, 3, 10), "event_amount": Decimal("200000000"),
        "contract_amount": Decimal("200000000"), "contract_currency": "KRW",
        "company_number": "2222222222", "company_name": "구성사",
        "participation_share_rate": Decimal("40"), "supplier_role_name": "구성사",
    }]
    notice = {
        "notice_name": "차세대 정보시스템 구축", "estimated_price": Decimal("200000000"),
        "allocated_budget": None, "as_of": datetime(2026, 9, 1, tzinfo=timezone.utc),
    }

    result = _organization_field_event_analysis(rows, notice, 5)

    assert result["event_deduplication"]["merged_award_contract_count"] == 1
    assert result["market_structure"]["award_event_count"] == 1
    assert result["market_structure"]["company_count"] == 2
    assert result["market_structure"]["top_1_share"] == 0.6
    assert result["company_metrics"]["1111111111"]["same_field_event_count"] == 1
    assert result["company_metrics"]["2222222222"]["same_field_contract_amount"] == 80000000
    assert result["company_metrics"]["1111111111"]["annual_activity"] == [{
        "year": 2025,
        "award_event_count": 1,
        "attributed_contract_amount": 120000000,
        "amount_completeness": "complete",
        "sole_count": 0,
        "consortium_lead_count": 1,
        "consortium_member_count": 0,
    }]
    assert result["company_metrics"]["2222222222"]["annual_activity"][0][
        "consortium_member_count"
    ] == 1
    event = result["events"][0]
    assert event["award_date"] == date(2025, 3, 1)
    assert event["contract_date"] == date(2025, 3, 10)


@pytest.mark.asyncio
async def test_project_lineage_keeps_structured_only_matches_as_candidates() -> None:
    result = await execute_bid_project_lineage(
        RegistryLoader(REGISTRIES).load(), "find_bid_project_lineage",
        {"bid_notice_id": "R26TEST:000", "period_years": 5},
        reader=SimilarNoticeReader(),
    )

    assert result.outcome["items"]
    assert all(item["relationship_type"] == "related_candidate" for item in result.outcome["items"])
    assert all(item["confirmation_status"] == "requires_source_evidence" for item in result.outcome["items"])
    assert result.outcome["policy"]["title_similarity_alone_confirms_lineage"] is False


@pytest.mark.asyncio
async def test_procurement_profiles_keep_event_types_and_attributed_amounts_separate() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            return [
                {
                    "activity_type": "participation", "event_key": "N1:C1",
                    "bid_notice_id": "N1:000", "notice_name": "정보시스템 구축",
                    "organization_code": "ORG-1", "organization_name": "기관",
                    "company_number": "1111111111", "company_name": "업체",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(2025, 1, 1), "event_amount": Decimal("90"),
                    "attributed_contract_amount": None, "amount_completeness": "unknown",
                },
                {
                    "activity_type": "award", "event_key": "N1:000:0:0",
                    "bid_notice_id": "N1:000", "notice_name": "정보시스템 구축",
                    "organization_code": "ORG-1", "organization_name": "기관",
                    "company_number": "1111111111", "company_name": "업체",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(2025, 2, 1), "event_amount": Decimal("90"),
                    "attributed_contract_amount": None, "amount_completeness": "unknown",
                },
                {
                    "activity_type": "contract", "event_key": "C1",
                    "bid_notice_id": "N1:000", "notice_name": "정보시스템 구축",
                    "organization_code": "ORG-1", "organization_name": "기관",
                    "company_number": "1111111111", "company_name": "업체",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "activity_date": date(2025, 3, 1), "event_amount": Decimal("100"),
                    "attributed_contract_amount": Decimal("60"),
                    "amount_completeness": "complete",
                },
            ]

    catalog = RegistryLoader(REGISTRIES).load()
    organization = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_years": 5}, reader=Reader(),
    )
    company = await execute_company_procurement_profile(
        catalog, "analyze_company_procurement_profile",
        {"business_registration_number": "1111111111", "period_years": 5}, reader=Reader(),
    )

    assert organization.outcome["summary"]["participation_count"] == 1
    assert organization.outcome["summary"]["award_event_count"] == 1
    assert organization.outcome["summary"]["contract_event_count"] == 1
    assert organization.outcome["summary"]["total_attributed_contract_amount"] == 60
    assert organization.outcome["analysis_basis"]["period_type"] == "calendar_fiscal_years"
    assert organization.outcome["analysis_basis"]["period_from"] == date(
        date.today().year - 4, 1, 1,
    )
    assert organization.outcome["company_relationships"][0]["major_fields"][0][
        "event_count"
    ] == 1
    assert organization.outcome["field_distribution_level"] == "large"
    assert organization.outcome["field_distribution"][0]["large_category"] == "ICT 서비스"
    assert organization.outcome["project_type_distribution"][0]["project_type"] == "build"
    assert organization.outcome["work_type_distribution"] == [{
        "work_type": "service", "work_type_name": "용역", "event_count": 3,
        "participation_count": 1, "award_event_count": 1, "contract_event_count": 1,
        "attributed_contract_amount": 60,
    }]
    assert organization.outcome["field_distribution"][0]["work_types"] == ["service"]
    assert company.outcome["organization_relationships"][0]["active_years"] == [2025]

    filtered = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1", "period_years": 5,
            "large_category": " ICT   서비스 ",
            "middle_category": "SW 및 시스템 개발",
            "field_code": "81111599", "work_type": "service",
        },
        reader=Reader(),
    )
    assert filtered.outcome["summary"]["contract_event_count"] == 1
    assert filtered.outcome["company_relationships"][0]["company_number"] == "1111111111"
    assert filtered.outcome["field_distribution_level"] == "detail"
    assert filtered.outcome["field_distribution"][0]["field_code"] == "81111599"
    assert filtered.outcome["analysis_basis"]["field_filter"]["field_name"] == (
        "정보시스템개발서비스"
    )


@pytest.mark.asyncio
async def test_company_profile_organization_search_is_relationship_list_only() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            return [{
                "activity_type": "contract", "event_key": f"C{index}",
                "bid_notice_id": f"N{index}:000", "notice_name": "정보시스템 계약",
                "organization_code": organization_code,
                "organization_name": organization_name,
                "company_number": "1111111111", "company_name": "업체",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service", "activity_date": date(2025, index, 1),
                "event_amount": Decimal(str(amount)),
                "attributed_contract_amount": Decimal(str(amount)),
                "amount_completeness": "complete",
            } for index, (organization_code, organization_name, amount) in enumerate((
                ("ORG-1", "근로 복지 공단", 300),
                ("ORG-2", "한국사회보장정보원", 200),
                ("ORG-3", "근로 복지 연구원", 100),
            ), start=1)]

    catalog = RegistryLoader(REGISTRIES).load()
    base_inputs = {
        "business_registration_number": "1111111111",
        "period_from_year": 2025, "period_to_year": 2025,
        "page": 1, "page_size": 1,
    }
    baseline = await execute_company_procurement_profile(
        catalog, "analyze_company_procurement_profile", base_inputs, reader=Reader(),
    )
    page_one = await execute_company_procurement_profile(
        catalog, "analyze_company_procurement_profile",
        {**base_inputs, "organization_query": "  근로 복지  "}, reader=Reader(),
    )
    page_two = await execute_company_procurement_profile(
        catalog, "analyze_company_procurement_profile",
        {**base_inputs, "organization_query": "근로 복지", "page": 2}, reader=Reader(),
    )

    assert page_one.outcome["pagination"]["total_items"] == 2
    assert page_one.outcome["pagination"]["total_pages"] == 2
    assert page_two.outcome["pagination"]["total_items"] == 2
    assert page_two.outcome["pagination"]["total_pages"] == 2
    assert page_one.outcome["organization_relationships"][0]["organization_name"] == (
        "근로 복지 공단"
    )
    assert page_two.outcome["organization_relationships"][0]["organization_name"] == (
        "근로 복지 연구원"
    )
    assert page_one.outcome["summary"] == baseline.outcome["summary"]
    assert page_one.outcome["yearly_activity"] == baseline.outcome["yearly_activity"]
    assert page_one.outcome["field_distribution"] == baseline.outcome["field_distribution"]
    assert page_one.outcome["analysis_basis"]["organization_query"] == "근로 복지"
    assert page_one.objects[0].properties["relationship_count"] == 2

    empty = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "field_code": "00000000"}, reader=Reader(),
    )
    assert empty.outcome["summary"]["notice_count"] == 0
    assert empty.outcome["company_relationships"] == []


@pytest.mark.asyncio
async def test_company_profile_filters_complete_target_year_organization_entry_set() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            base = {
                "activity_type": "contract",
                "company_number": "1111111111",
                "company_name": "업체",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service",
                "amount_completeness": "complete",
                "attribution_date_basis": "first_contract_date",
                "contract_method_name": "일반경쟁",
            }
            definitions = (
                ("NEW-A", "ORG-NEW-A", "신규 기관 A", 2026, 1, 100),
                ("NEW-B", "ORG-NEW-B", "신규 기관 B", 2026, 2, 200),
                ("RETURN-OLD", "ORG-RETURN", "재진입 기관", 2021, 1, 50),
                ("RETURN-NOW", "ORG-RETURN", "재진입 기관", 2026, 3, 300),
                ("CURRENT-OLD", "ORG-CURRENT", "기존 기관", 2024, 1, 70),
                ("CURRENT-NOW", "ORG-CURRENT", "기존 기관", 2026, 4, 400),
                ("NO-TARGET", "ORG-NO-TARGET", "대상연도 계약 없음", 2025, 1, 80),
            )
            return [{
                **base,
                "event_key": event_key,
                "bid_notice_id": f"{event_key}:000",
                "notice_name": f"{organization_name} 계약",
                "organization_code": organization_code,
                "organization_name": organization_name,
                "activity_date": date(year, month, 1),
                "notice_published_date": date(year, month, 1),
                "first_contract_date": date(year, month, 1),
                "latest_contract_version_date": date(year, month, 1),
                "event_amount": Decimal(amount),
                "attributed_contract_amount": Decimal(amount),
            } for (
                event_key, organization_code, organization_name, year, month, amount
            ) in definitions]

    catalog = RegistryLoader(REGISTRIES).load()
    base_inputs = {
        "business_registration_number": "1111111111",
        "period_from_year": 2021,
        "period_to_year": 2026,
        "target_year": 2026,
        "organization_entry_status": "first_observed",
        "work_type": "service",
        "large_category": "ICT 서비스",
        "middle_category": "SW 및 시스템 개발",
        "field_code": "81111599",
        "page_size": 1,
    }
    page_one = await execute_company_procurement_profile(
        catalog, "analyze_company_procurement_profile",
        {**base_inputs, "page": 1}, reader=Reader(),
    )
    page_two = await execute_company_procurement_profile(
        catalog, "analyze_company_procurement_profile",
        {**base_inputs, "page": 2}, reader=Reader(),
    )

    entry = page_one.outcome["organization_entry"]
    assert entry["first_observed_organization_count"] == 2
    assert entry["reentering_organization_count"] == 1
    assert entry["incumbent_organization_count"] == 1
    assert entry["total_organization_count"] == 4
    assert entry["first_observed_organization_rate"] == 0.5
    assert page_one.outcome["summary"]["organization_entry"] == entry
    assert page_one.outcome["pagination"]["total_items"] == 2
    assert page_one.outcome["pagination"]["total_pages"] == 2
    assert page_two.outcome["pagination"]["total_items"] == 2
    returned = page_one.outcome["organization_relationships"] + page_two.outcome[
        "organization_relationships"
    ]
    assert {item["organization_code"] for item in returned} == {
        "ORG-NEW-A", "ORG-NEW-B",
    }
    assert all(
        item["organization_entry_status"] == "first_observed" for item in returned
    )
    assert all(
        item["organization_entry"]["organization_entry_status"] == "first_observed"
        for item in returned
    )
    assert page_one.outcome["summary"]["organization_count"] == 5
    assert page_one.outcome["analysis_basis"]["organization_entry_target_year"] == 2026
    assert page_one.outcome["analysis_basis"]["organization_entry_status"] == (
        "first_observed"
    )

    reentering = await execute_company_procurement_profile(
        catalog, "analyze_company_procurement_profile",
        {**base_inputs, "organization_entry_status": "reentering", "page": 1},
        reader=Reader(),
    )
    incumbent = await execute_company_procurement_profile(
        catalog, "analyze_company_procurement_profile",
        {**base_inputs, "organization_entry_status": "incumbent", "page": 1},
        reader=Reader(),
    )
    assert reentering.outcome["pagination"]["total_items"] == 1
    assert reentering.outcome["organization_relationships"][0][
        "organization_code"
    ] == "ORG-RETURN"
    assert incumbent.outcome["pagination"]["total_items"] == 1
    assert incumbent.outcome["organization_relationships"][0][
        "organization_code"
    ] == "ORG-CURRENT"


@pytest.mark.asyncio
async def test_procurement_profile_merges_contract_versions_by_project() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            return [{
                "activity_type": "contract", "event_key": event_key,
                "bid_notice_id": "N1:000", "notice_name": "정보시스템 유지관리",
                "organization_code": "ORG-1", "organization_name": "기관",
                "company_number": "1111111111", "company_name": "업체",
                "procurement_classification_number": "81111899",
                "procurement_classification_name": "정보시스템유지관리서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "정보시스템 운영",
                "work_type": "service", "activity_date": date(2023, 1, 1),
                "attribution_date_basis": "notice_published_at",
                "first_contract_date": date(2023, 2, 1),
                "latest_contract_version_date": activity_date,
                "event_amount": amount, "attributed_contract_amount": amount,
                "amount_completeness": "complete",
            } for event_key, activity_date, amount in (
                ("C1", date(2023, 1, 1), Decimal("80")),
                ("C1", date(2025, 1, 1), Decimal("100")),
            )]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_years": 5}, reader=Reader(),
    )

    relationship = result.outcome["company_relationships"][0]
    assert relationship["contract_event_count"] == 1
    assert relationship["contract_version_count"] == 2
    assert relationship["unique_project_count"] == 1
    assert relationship["total_attributed_contract_amount"] == 100
    assert relationship["active_years"] == [2023]
    assert relationship["latest_contract_date"] == date(2025, 1, 1)
    assert relationship["yearly_activity"] == [{
        "year": 2023, "participation_count": 0, "award_event_count": 0,
        "result_confirmed_participation_count": 0,
        "successful_participation_count": 0, "award_success_rate": None,
        "contract_event_count": 1, "attributed_contract_amount": 100,
        "amount_completeness": "complete",
    }]
    representative = relationship["representative_notices"][0]
    assert representative["attribution_date"] == date(2023, 2, 1)
    assert representative["first_contract_date"] == date(2023, 2, 1)
    assert representative["latest_contract_version_date"] == date(2025, 1, 1)
    assert result.outcome["summary"]["contract_event_count"] == 1
    assert result.outcome["summary"]["contract_version_count"] == 2
    assert result.outcome["summary"]["unique_project_count"] == 1


@pytest.mark.asyncio
async def test_procurement_profile_uses_first_contract_year_and_reports_missing_date() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            common = {
                "activity_type": "contract",
                "bid_notice_id": "N1:000",
                "notice_name": "장기 정보시스템 계약",
                "organization_code": "ORG-1",
                "organization_name": "기관",
                "company_number": "1111111111",
                "company_name": "업체",
                "procurement_classification_number": "81111899",
                "procurement_classification_name": "정보시스템유지관리서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "정보시스템 운영",
                "work_type": "service",
                "attributed_contract_amount": Decimal("120"),
                "event_amount": Decimal("120"),
                "amount_completeness": "complete",
                "contract_version_count": 1,
            }
            return [
                {
                    **common,
                    "event_key": "CONTRACT-1",
                    "activity_date": date(2022, 11, 1),
                    "attribution_date_basis": "notice_published_at",
                    "first_contract_date": date(2023, 2, 1),
                    "latest_contract_version_date": date(2025, 6, 1),
                },
                {
                    **common,
                    "event_key": "CONTRACT-MISSING-DATE",
                    "activity_date": date(2024, 3, 1),
                    "attribution_date_basis": "notice_published_at",
                    "first_contract_date": None,
                    "latest_contract_version_date": None,
                },
            ]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2023,
            "period_to_year": 2025,
        },
        reader=Reader(),
    )

    assert result.outcome["summary"]["contract_event_count"] == 1
    assert result.outcome["summary"]["missing_first_contract_date_count"] == 1
    assert result.outcome["summary"]["total_attributed_contract_amount"] == 120
    assert "some_contract_events_missing_first_contract_date" in result.outcome[
        "data_completeness"
    ]["missing_reasons"]
    assert result.outcome["yearly_activity"][0]["year"] == 2023
    assert result.outcome["yearly_activity"][0]["attributed_contract_amount"] == 120
    assert result.outcome["company_relationships"][0]["latest_contract_date"] == date(
        2025, 6, 1
    )
    assert result.outcome["analysis_basis"] | {
        "contract_event_date_basis": "first_contract_date",
        "contract_amount_basis": "latest_version_at_or_before_period_end",
        "contract_amount_year_attribution": "first_contract_year",
        "contract_version_deduplication": "merged_by_contract_event",
    } == result.outcome["analysis_basis"]


@pytest.mark.asyncio
async def test_procurement_profile_yearly_metrics_use_separate_date_bases() -> None:
    classification = {
        "procurement_classification_number": "81111599",
        "procurement_classification_name": "정보시스템개발서비스",
        "procurement_large_classification_name": "ICT 서비스",
        "procurement_middle_classification_name": "SW 및 시스템 개발",
        "work_type": "service",
    }

    class Reader:
        def activities(self, catalog, **kwargs):
            common = {
                "bid_notice_id": "N1:000", "notice_name": "연도 기준 검증",
                "notice_published_date": date(2023, 3, 1),
                "organization_code": "ORG-1", "organization_name": "기관",
                "company_number": "1111111111", "company_name": "업체",
                "event_amount": None, "attributed_contract_amount": None,
                "amount_completeness": "unknown", **classification,
            }
            return [
                {
                    **common, "activity_type": "participation", "event_key": "N1:000",
                    "activity_date": date(2023, 3, 1),
                    "attribution_date_basis": "notice_published_at",
                    "result_confirmed": True, "participation_successful": True,
                },
                {
                    **common, "activity_type": "award", "event_key": "N1:000:0:0",
                    "activity_date": date(2024, 4, 1),
                    "attribution_date_basis": "final_award_date_or_opening_at",
                    "result_confirmed": True, "participation_successful": True,
                },
                {
                    **common, "activity_type": "contract", "event_key": "C1",
                    "activity_date": date(2025, 5, 1),
                    "first_contract_date": date(2025, 5, 1),
                    "latest_contract_version_date": date(2025, 6, 1),
                    "attribution_date_basis": "first_contract_date",
                    "event_amount": Decimal("130"),
                    "attributed_contract_amount": Decimal("130"),
                    "amount_completeness": "complete", "contract_version_count": 2,
                },
            ]

        def notice_publications(self, catalog, **kwargs):
            return [
                {
                    "bid_notice_id": "N1:000", "notice_name": "연도 기준 검증",
                    "notice_published_date": date(2023, 3, 1), **classification,
                },
                {
                    "bid_notice_id": "N2:000", "notice_name": "활동 없는 공고",
                    "notice_published_date": date(2024, 7, 1), **classification,
                },
            ]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(),
        "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2023,
            "period_to_year": 2025,
        },
        reader=Reader(),
    )

    yearly = {item["year"]: item for item in result.outcome["yearly_activity"]}
    assert result.outcome["summary"]["notice_count"] == 2
    assert sum(item["notice_count"] for item in yearly.values()) == 2
    assert yearly[2023]["notice_count"] == 1
    assert yearly[2024]["notice_count"] == 1
    assert yearly[2024]["award_event_count"] == 1
    assert yearly[2025]["contract_event_count"] == 1
    assert yearly[2025]["attributed_contract_amount"] == 130
    assert yearly[2025]["company_count"] == 1
    assert yearly[2023]["company_count"] == 0
    assert yearly[2024]["company_count"] == 0
    assert result.outcome["analysis_basis"] | {
        "notice_year_basis": "notice_published_at",
        "award_year_basis": "final_award_date_or_opening_at",
        "contract_year_basis": "first_contract_date",
    } == result.outcome["analysis_basis"]


@pytest.mark.asyncio
async def test_procurement_profile_applies_explicit_year_range_everywhere() -> None:
    class Reader:
        observed_period = None

        def activities(self, catalog, **kwargs):
            self.observed_period = (kwargs["period_from"], kwargs["period_to"])
            return [
                {
                    "activity_type": "contract", "event_key": f"C-{year}",
                    "bid_notice_id": f"N-{year}:000", "notice_name": f"사업 {year}",
                    "organization_code": "ORG-1", "organization_name": "기관",
                    "company_number": f"{year:010d}", "company_name": f"업체 {year}",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service", "activity_date": date(year, 6, 1),
                    "event_amount": Decimal(str(year)),
                    "attributed_contract_amount": Decimal(str(year)),
                    "amount_completeness": "complete",
                }
                for year in (2022, 2023, 2024, 2025, 2026)
                if kwargs["period_from"] <= date(year, 6, 1) < kwargs["period_to"]
            ]

        def organization_award_history(self, catalog, **kwargs):
            assert kwargs["history_from"] == date(2020, 1, 1)
            assert kwargs["history_to"] == date(2026, 1, 1)
            assert kwargs["work_type"] is None
            assert kwargs["large_category"] is None
            assert kwargs["middle_category"] is None
            assert kwargs["field_code"] is None
            return {}, kwargs["history_from"]

    reader = Reader()
    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1", "period_years": 5,
            "period_from_year": 2023, "period_to_year": 2025,
        }, reader=reader,
    )

    assert reader.observed_period == (date(2020, 1, 1), date(2026, 1, 1))
    assert result.outcome["summary"]["contract_event_count"] == 3
    assert result.outcome["pagination"]["total_items"] == 3
    assert [item["year"] for item in result.outcome["yearly_activity"]] == [2025, 2024, 2023]
    assert result.outcome["field_distribution"][0]["contract_event_count"] == 3
    assert result.outcome["work_type_distribution"][0]["contract_event_count"] == 3
    assert {
        key: result.outcome["analysis_basis"][key]
        for key in (
            "period_from", "period_to", "period_from_year", "period_to_year",
            "period_years", "period_type",
        )
    } == {
        "period_from": date(2023, 1, 1),
        "period_to": date(2025, 12, 31),
        "period_from_year": 2023,
        "period_to_year": 2025,
        "period_years": 3,
        "period_type": "explicit_calendar_year_range",
    }
    rolling = result.outcome["summary"]["rolling_12m_supplier_entry"]
    assert rolling["period_from"] == date(2025, 1, 1)
    assert rolling["period_to"] == date(2026, 1, 1)


@pytest.mark.asyncio
async def test_procurement_profile_rejects_incomplete_or_reversed_year_range() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    with pytest.raises(CapabilityExecutionError, match="must be provided together"):
        await execute_company_procurement_profile(
            catalog, "analyze_company_procurement_profile",
            {"business_registration_number": "1111111111", "period_from_year": 2023},
        )
    with pytest.raises(CapabilityExecutionError, match="less than or equal"):
        await execute_company_procurement_profile(
            catalog, "analyze_company_procurement_profile",
            {
                "business_registration_number": "1111111111",
                "period_from_year": 2025, "period_to_year": 2023,
            },
        )


@pytest.mark.asyncio
async def test_organization_profile_lists_only_contracted_companies() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            base = {
                "notice_name": "조달 사업", "organization_code": "ORG-1",
                "organization_name": "기관", "work_type": "service",
                "procurement_classification_number": None,
                "procurement_classification_name": None,
                "procurement_large_classification_name": None,
                "procurement_middle_classification_name": None,
                "event_amount": Decimal("100"), "amount_completeness": "unknown",
            }
            return [
                {
                    **base, "activity_type": "participation", "event_key": "P-ONLY",
                    "bid_notice_id": "P:000", "company_number": "1111111111",
                    "company_name": "참여만", "activity_date": date(2025, 1, 1),
                    "attributed_contract_amount": None,
                },
                {
                    **base, "activity_type": "award", "event_key": "A-ONLY",
                    "bid_notice_id": "A:000", "company_number": "2222222222",
                    "company_name": "낙찰만", "activity_date": date(2025, 2, 1),
                    "attributed_contract_amount": None,
                },
                {
                    **base, "activity_type": "participation", "event_key": "P-C",
                    "bid_notice_id": "C:000", "company_number": "3333333333",
                    "company_name": "계약업체", "activity_date": date(2025, 3, 1),
                    "attributed_contract_amount": None,
                },
                {
                    **base, "activity_type": "contract", "event_key": "C-0",
                    "bid_notice_id": "C:000", "company_number": "3333333333",
                    "company_name": "계약업체", "activity_date": date(2020, 4, 1),
                    "attributed_contract_amount": Decimal("80"),
                    "amount_completeness": "complete",
                },
                {
                    **base, "activity_type": "contract", "event_key": "C-1",
                    "bid_notice_id": "C:000", "company_number": "3333333333",
                    "company_name": "계약업체", "activity_date": date(2025, 4, 1),
                    "attributed_contract_amount": Decimal("100"),
                    "amount_completeness": "complete",
                },
            ]

        def organization_award_history(self, catalog, **kwargs):
            return {}, kwargs["history_from"]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_from_year": 2025, "period_to_year": 2025},
        reader=Reader(),
    )

    assert result.outcome["summary"]["participation_count"] == 2
    assert result.outcome["summary"]["award_event_count"] == 1
    assert result.outcome["summary"]["company_count"] == 1
    assert result.outcome["summary"]["company_count_basis"] == "contracted_companies"
    assert result.outcome["pagination"]["total_items"] == 1
    assert len(result.outcome["company_relationships"]) == 1
    relationship = result.outcome["company_relationships"][0]
    assert relationship["company_name"] == "계약업체"
    assert relationship["contract_event_count"] == 1
    assert relationship["participation_count"] == 1
    assert result.outcome["yearly_activity"][0]["company_count"] == 1
    rolling = result.outcome["summary"]["rolling_12m_supplier_entry"]
    assert rolling["total_company_count"] == 1
    assert rolling["classified_company_count"] == 1
    assert sum(rolling[key] for key in (
        "first_observed_company_count", "reentering_company_count",
        "incumbent_company_count",
    )) == rolling["total_company_count"]


@pytest.mark.asyncio
async def test_organization_profile_company_search_sort_and_pagination_are_list_only() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            rows = []
            definitions = [
                ("1111111111", "알파 시스템", [("A-1", date(2025, 2, 1), "40"),
                                                ("A-2", date(2025, 5, 1), "60")]),
                ("2222222222", "베타정보", [("B-1", date(2025, 3, 1), "300")]),
                ("3333333333", "감마테크", [("C-1", date(2025, 8, 1), "200")]),
            ]
            for company_number, company_name, contracts in definitions:
                for event_key, activity_date, amount in contracts:
                    rows.append({
                        "activity_type": "contract", "event_key": event_key,
                        "bid_notice_id": f"{event_key}:000", "notice_name": event_key,
                        "organization_code": "ORG-1", "organization_name": "기관",
                        "company_number": company_number, "company_name": company_name,
                        "procurement_classification_number": None,
                        "procurement_classification_name": None,
                        "procurement_large_classification_name": None,
                        "procurement_middle_classification_name": None,
                        "work_type": "service", "activity_date": activity_date,
                        "event_amount": Decimal(amount),
                        "attributed_contract_amount": Decimal(amount),
                        "amount_completeness": "complete",
                    })
            return rows

    catalog = RegistryLoader(REGISTRIES).load()
    base_inputs = {
        "organization_code": "ORG-1", "period_from_year": 2025,
        "period_to_year": 2025, "page": 1, "page_size": 20,
    }
    baseline = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile", base_inputs, reader=Reader(),
    )
    searched = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile", {
            **base_inputs, "company_query": "  알파   ", "sort": "contract_count_desc",
        }, reader=Reader(),
    )

    assert searched.outcome["pagination"]["total_items"] == 1
    assert searched.outcome["pagination"]["total_pages"] == 1
    assert searched.outcome["pagination"]["sort"] == "contract_count_desc"
    assert searched.outcome["company_relationships"][0]["company_name"] == "알파 시스템"
    assert searched.outcome["company_relationships"][0]["latest_contract_date"] == date(
        2025, 5, 1,
    )
    assert searched.outcome["summary"] == baseline.outcome["summary"]
    assert searched.outcome["yearly_activity"] == baseline.outcome["yearly_activity"]
    assert searched.outcome["field_distribution"] == baseline.outcome["field_distribution"]
    assert searched.outcome["work_type_distribution"] == baseline.outcome[
        "work_type_distribution"
    ]
    assert searched.outcome["company_structure"] == baseline.outcome["company_structure"]
    assert searched.outcome["notice_quarter_distribution"] == baseline.outcome[
        "notice_quarter_distribution"
    ]
    assert searched.outcome["contract_method_distribution"] == baseline.outcome[
        "contract_method_distribution"
    ]
    assert searched.objects[0].properties["relationship_count"] == 3

    expected_orders = {
        "contract_amount_desc": ["베타정보", "감마테크", "알파 시스템"],
        "contract_count_desc": ["알파 시스템", "베타정보", "감마테크"],
        "latest_contract_desc": ["감마테크", "알파 시스템", "베타정보"],
    }
    for sort, expected in expected_orders.items():
        result = await execute_organization_procurement_profile(
            catalog, "analyze_organization_procurement_profile", {
                **base_inputs, "sort": sort,
            }, reader=Reader(),
        )
        assert [
            item["company_name"] for item in result.outcome["company_relationships"]
        ] == expected


@pytest.mark.asyncio
async def test_organization_profile_market_structure_uses_unique_contract_events() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            base = {
                "organization_code": "ORG-1", "organization_name": "기관",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service", "amount_completeness": "complete",
                "activity_type": "contract", "attribution_date_basis": "notice_published_at",
            }
            return [
                {**base, "event_key": "OLD", "bid_notice_id": "OLD:000",
                 "notice_name": "이전 사업", "company_number": "1111111111",
                 "company_name": "A사", "activity_date": date(2024, 2, 1),
                 "notice_published_date": date(2024, 2, 1),
                 "contract_method_name": "일반경쟁", "event_amount": Decimal("100"),
                 "attributed_contract_amount": Decimal("100")},
                {**base, "event_key": "JOINT", "bid_notice_id": "JOINT:000",
                 "notice_name": "공동 사업", "company_number": "1111111111",
                 "company_name": "A사", "activity_date": date(2025, 4, 1),
                 "notice_published_date": date(2025, 4, 1),
                 "contract_method_name": "제한경쟁", "event_amount": Decimal("100"),
                 "attributed_contract_amount": Decimal("60")},
                {**base, "event_key": "JOINT", "bid_notice_id": "JOINT:000",
                 "notice_name": "공동 사업", "company_number": "2222222222",
                 "company_name": "B사", "activity_date": date(2025, 4, 1),
                 "notice_published_date": date(2025, 4, 1),
                 "contract_method_name": "제한경쟁", "event_amount": Decimal("100"),
                 "attributed_contract_amount": Decimal("40")},
                {**base, "event_key": "DIRECT", "bid_notice_id": "DIRECT:000",
                 "notice_name": "수의 사업", "company_number": "1111111111",
                 "company_name": "A사", "activity_date": date(2025, 8, 1),
                 "notice_published_date": date(2025, 8, 1),
                 "contract_method_name": "수의계약", "event_amount": Decimal("200"),
                 "attributed_contract_amount": Decimal("200")},
            ]

        def organization_award_history(self, catalog, **kwargs):
            return {"1111111111": date(2024, 2, 1), "2222222222": date(2025, 4, 1)}, date(2020, 1, 1)

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_from_year": 2024, "period_to_year": 2025},
        reader=Reader(),
    )

    outcome = result.outcome
    assert outcome["summary"]["average_contract_amount"] == 400 / 3
    assert outcome["summary"]["previous_period_comparison"] == {
        "basis": "year_over_year", "current_year": 2025, "comparison_year": 2024,
        "contract_amount_change_rate": 2.0, "contract_event_count_change": 1,
        "comparable": True, "comparison_note": None,
    }
    assert sum(item["contract_event_count"] for item in outcome["field_distribution"]) == 3
    assert sum(item["notice_count"] for item in outcome["notice_quarter_distribution"]) == 3
    assert sum(
        item["contract_event_count"] for item in outcome["contract_method_distribution"]
    ) == 3
    assert outcome["company_structure"]["contracted_company_count"] == 2
    assert outcome["company_structure"]["multi_contract_company_count"] == 1
    assert outcome["company_structure"]["single_contract_company_count"] == 1
    assert outcome["company_structure"]["top_5_company_amount"] == 400
    assert outcome["company_structure"]["top_5_company_amount_share"] == 1.0
    assert outcome["company_relationships"][0]["major_field"] == {
        "field_code": "81111599", "field_name": "정보시스템개발서비스",
    }


@pytest.mark.asyncio
async def test_supplier_entry_uses_target_year_and_three_prior_calendar_years() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            base = {
                "activity_type": "contract", "organization_code": "ORG-1",
                "organization_name": "기관", "notice_name": "정보시스템 사업",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service", "amount_completeness": "complete",
                "attribution_date_basis": "notice_published_at",
            }
            definitions = [
                ("A", "1111111111", "신규", 2026, "100"),
                ("B-OLD", "2222222222", "재진입", 2022, "10"),
                ("B", "2222222222", "재진입", 2026, "200"),
                ("C-OLD", "3333333333", "기존", 2024, "50"),
                ("C", "3333333333", "기존", 2026, "300"),
            ]
            return [{
                **base, "event_key": event, "bid_notice_id": f"{event}:000",
                "company_number": number, "company_name": name,
                "activity_date": date(year, 4, 1),
                "notice_published_date": date(year, 4, 1),
                "first_contract_date": date(year, 6, 1),
                "latest_contract_version_date": date(year, 9, 1),
                "event_amount": Decimal(amount),
                "attributed_contract_amount": Decimal(amount),
                "contract_method_name": "일반경쟁",
            } for event, number, name, year, amount in definitions]

        def organization_award_history(self, catalog, **kwargs):
            return {
                "1111111111": date(2026, 4, 1),
                "2222222222": date(2022, 4, 1),
                "3333333333": date(2024, 4, 1),
            }, date(2020, 1, 1)

    catalog = RegistryLoader(REGISTRIES).load()
    inputs = {
        "organization_code": "ORG-1", "period_from_year": 2023,
        "period_to_year": 2026, "work_type": "service",
        "large_category": "ICT 서비스",
    }
    result = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile", inputs, reader=Reader(),
    )
    entry = result.outcome["supplier_entry"]
    assert entry["lookback_from"] == date(2023, 1, 1)
    assert entry["lookback_to"] == date(2025, 12, 31)
    assert entry["first_observed_company_count"] == 1
    assert entry["reentering_company_count"] == 1
    assert entry["incumbent_company_count"] == 1
    assert entry["entry_and_reentry_company_count"] == 2
    assert entry["total_company_count"] == 3
    assert entry["entry_and_reentry_rate"] == pytest.approx(2 / 3, abs=1e-6)
    assert entry["history_complete_for_lookback"] is True
    structure = result.outcome["company_structure"]
    assert structure["single_contract_company_count"] + structure[
        "multi_contract_company_count"
    ] == structure["contracted_company_count"]
    assert structure["top_5_company_amount"] == 650
    assert structure["total_company_attributed_contract_amount"] == 650
    assert structure["top_5_company_amount_share"] == 1.0
    assert structure["small_supplier_population"] is True
    assert 0 <= structure["hhi"] <= 10000

    search = await execute_organization_supplier_entry_search(
        catalog, "search_organization_supplier_entries", {
            "organization_code": "ORG-1", "target_year": 2026,
            "work_type": "service", "large_category": "ICT 서비스",
            "entry_status": "reentering", "page": 1, "page_size": 20,
        }, reader=Reader(),
    )
    assert search.outcome["pagination"]["total_items"] == 1
    assert search.outcome["items"][0]["company_name"] == "재진입"
    assert search.outcome["items"][0]["target_year_first_contract_date"] == date(2026, 6, 1)
    assert search.outcome["items"][0]["target_year_latest_contract_date"] == date(2026, 6, 1)
    assert search.outcome["items"][0]["previous_contract_date"] == date(2022, 6, 1)
    assert search.outcome["items"][0]["reentry_contract_date"] == date(2026, 6, 1)


@pytest.mark.asyncio
async def test_supplier_entry_searches_sorts_and_pages_the_complete_supplier_set() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            rows = []
            for index in range(105):
                company_number = str(1000000000 + index)
                amount = None if index == 104 else Decimal("0" if index == 103 else index + 1)
                rows.append({
                    "activity_type": "contract",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    "notice_name": f"정보시스템 사업 {index:03d}",
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "work_type": "service",
                    "amount_completeness": "unknown" if amount is None else "complete",
                    "attribution_date_basis": "first_contract_date",
                    "event_key": f"CONTRACT-{index:03d}",
                    "bid_notice_id": f"NOTICE-{index:03d}:000",
                    "company_number": company_number,
                    "company_name": (
                        f"한글검색 업체 {index:03d}" if index < 27 else f"일반 업체 {index:03d}"
                    ),
                    "activity_date": date(2026, 1, 1) + timedelta(days=index),
                    "notice_published_date": date(2025, 12, 1),
                    "first_contract_date": date(2026, 1, 1) + timedelta(days=index),
                    "latest_contract_version_date": date(2026, 1, 1) + timedelta(days=index),
                    "event_amount": amount,
                    "attributed_contract_amount": amount,
                    "contract_method_name": "일반경쟁",
                })
            return rows

        def organization_award_history(self, catalog, **kwargs):
            return {
                str(1000000000 + index): date(2026, 1, 1) + timedelta(days=index)
                for index in range(105)
            }, date(2020, 1, 1)

    catalog = RegistryLoader(REGISTRIES).load()
    base_inputs = {
        "organization_code": "ORG-1",
        "target_year": 2026,
        "entry_status": "first_observed",
        "work_type": "service",
        "large_category": "ICT 서비스",
        "middle_category": "SW 및 시스템 개발",
        "field_code": "81111599",
    }

    observed_numbers = []
    for page in range(1, 12):
        result = await execute_organization_supplier_entry_search(
            catalog, "search_organization_supplier_entries",
            {**base_inputs, "page": page, "page_size": 10}, reader=Reader(),
        )
        assert result.outcome["pagination"]["total_items"] == 105
        assert result.outcome["pagination"]["total_pages"] == 11
        observed_numbers.extend(item["company_number"] for item in result.outcome["items"])
    assert len(observed_numbers) == len(set(observed_numbers)) == 105
    assert len(result.outcome["items"]) == 5

    korean = await execute_organization_supplier_entry_search(
        catalog, "search_organization_supplier_entries",
        {
            **base_inputs, "company_query": "  한글검색  ",
            "sort": "company_name_asc", "page": 2, "page_size": 10,
        }, reader=Reader(),
    )
    assert korean.outcome["pagination"] == {
        "page": 2, "page_size": 10, "total_items": 27, "total_pages": 3,
        "sort": "company_name_asc",
    }
    assert korean.outcome["supplier_entry"]["first_observed_company_count"] == 105
    assert korean.outcome["items"][0]["company_name"] == "한글검색 업체 010"

    number = await execute_organization_supplier_entry_search(
        catalog, "search_organization_supplier_entries",
        {**base_inputs, "company_query": "100-000-0007", "page": 1, "page_size": 10},
        reader=Reader(),
    )
    assert [item["company_number"] for item in number.outcome["items"]] == ["1000000007"]

    latest = await execute_organization_supplier_entry_search(
        catalog, "search_organization_supplier_entries",
        {**base_inputs, "sort": "latest_contract_desc", "page": 1, "page_size": 10},
        reader=Reader(),
    )
    assert latest.outcome["items"][0]["company_number"] == "1000000104"

    amount_zero = await execute_organization_supplier_entry_search(
        catalog, "search_organization_supplier_entries",
        {**base_inputs, "company_query": "1000000103", "page": 1, "page_size": 10},
        reader=Reader(),
    )
    amount_unknown = await execute_organization_supplier_entry_search(
        catalog, "search_organization_supplier_entries",
        {**base_inputs, "company_query": "1000000104", "page": 1, "page_size": 10},
        reader=Reader(),
    )
    assert amount_zero.outcome["items"][0]["target_year_attributed_contract_amount"] == 0
    assert amount_unknown.outcome["items"][0]["target_year_attributed_contract_amount"] is None
    assert amount_unknown.outcome["items"][0]["amount_completeness"] == "unknown"


@pytest.mark.asyncio
async def test_company_participation_search_and_competitors_share_filters() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            return [{
                "bid_notice_id": "N1:000", "notice_name": "정보시스템 사업",
                "organization_code": "ORG", "organization_name": "기관",
                "participant_name": "대상", "participation_date": date(2025, 5, 1),
                "rank": 2, "participant_count": 7, "bid_amount": Decimal("90"),
                "winning_amount": Decimal("100"), "result": "unsuccessful",
                "result_confirmed": True, "work_type": "service",
                "field_code": "81111599", "field_name": "정보시스템개발서비스",
                "large_category": "ICT 서비스", "middle_category": "SW 및 시스템 개발",
                "classification_source": "procurement_classification",
            }]

        def competitors(self, catalog, **kwargs):
            return [{
                "company_number": "2222222222", "company_name": "경쟁사",
                "bid_notice_id": "N1:000", "participation_date": date(2025, 5, 1),
                "participation_event_id": "N1:000:0:0", "work_type": "service",
                "field_code": "81111599", "field_name": "정보시스템개발서비스",
                "large_category": "ICT 서비스", "middle_category": "SW 및 시스템 개발",
                "classification_source": "procurement_classification",
            }]

    inputs = {"business_registration_number": "1111111111", "period_from_year": 2025,
              "period_to_year": 2025, "work_type": "service",
              "large_category": "ICT 서비스", "page": 1, "page_size": 20}
    catalog = RegistryLoader(REGISTRIES).load()
    history = await execute_company_participation_search(
        catalog, "search_bid_participations", inputs, reader=Reader(),
    )
    assert history.outcome["items"][0]["result"] == "unsuccessful"
    assert history.outcome["items"][0]["participant_count"] == 7
    competitors = await execute_company_competitor_analysis(
        catalog, "analyze_company_competitors", inputs, reader=Reader(),
    )
    assert competitors.outcome["items"][0]["co_participation_count"] == 1


@pytest.mark.asyncio
async def test_bid_notice_participations_reports_stored_completeness() -> None:
    class Reader:
        def find(self, catalog, **kwargs):
            assert kwargs == {"notice_number": "R26TEST", "notice_order": "000"}
            return [{
                "bid_notice_id": "R26TEST:000", "notice_name": "테스트 공고",
                "bid_classification_number": "1", "rebid_number": "000",
                "source_participant_count": 2,
                "winner_business_registration_number": "1111111111",
                "participation_id": "P1", "business_registration_number": "1111111111",
                "participant_name": "낙찰사", "opening_rank": 1,
                "bid_amount": Decimal("90"), "bid_rate": Decimal("90.1"),
                "result": "award", "result_confirmed": True,
            }]

    catalog = RegistryLoader(REGISTRIES).load()
    result = await execute_bid_notice_participations(
        catalog, "get_bid_notice_participations", {"bid_notice_id": "R26TEST:000"},
        reader=Reader(),
    )
    event = result.outcome["opening_events"][0]
    assert event["source_participant_count"] == 2
    assert event["stored_participant_count"] == 1
    assert event["returned_participant_count"] == 1
    assert event["data_completeness"] == {
        "status": "partial",
        "missing_reasons": ["stored_participant_count_less_than_source_participant_count"],
    }
    assert result.outcome["data_completeness"]["status"] == "partial"


@pytest.mark.asyncio
async def test_bid_participation_context_uses_prepublication_contract_market() -> None:
    class Reader:
        def bid_context(self, catalog, **kwargs):
            return ({"notice_name": "현재 사업", "organization_code": "ORG",
                "organization_name": "기관", "notice_published_date": date(2026, 7, 1),
                "work_type": "service", "field_code": "81111599",
                "large_category": "ICT 서비스", "middle_category": "SW 및 시스템 개발",
                "allocated_budget": Decimal("1000"), "estimated_price": Decimal("900"),
                "base_amount": None}, [])

        def activities(self, catalog, **kwargs):
            common = {"organization_code": "ORG", "organization_name": "기관",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "purchase_items": None, "work_type": "service",
                "attribution_date_basis": "notice_published_at", "contract_version_count": 1,
                "contract_version_dates": [], "result_confirmed": True,
                "participation_successful": True}
            return [{**common, "activity_type": "contract", "event_key": "C1",
                "bid_notice_id": "OLD1:000", "notice_name": "과거 사업",
                "company_number": "1111111111", "company_name": "A사",
                "activity_date": date(2026, 3, 1), "notice_published_date": date(2026, 3, 1),
                "event_amount": Decimal("500"), "attributed_contract_amount": Decimal("500"),
                "amount_completeness": "complete", "first_contract_date": date(2026, 4, 1),
                "latest_contract_version_date": date(2026, 4, 1)},
                {**common, "activity_type": "award", "event_key": "A1",
                "bid_notice_id": "OLD1:000", "notice_name": "과거 사업",
                "company_number": "1111111111", "company_name": "A사",
                "activity_date": date(2026, 3, 1), "notice_published_date": date(2026, 3, 1),
                "event_amount": Decimal("480"), "attributed_contract_amount": None,
                "amount_completeness": "unknown", "first_contract_date": None,
                "latest_contract_version_date": None}]

        def notice_publications(self, catalog, **kwargs):
            return [{"bid_notice_id": "OLD1:000", "notice_name": "과거 사업",
                "notice_published_date": date(2026, 3, 1), "allocated_budget": Decimal("500"),
                "estimated_price": Decimal("450"), "base_amount": None,
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "purchase_items": None, "work_type": "service"}]

        def bid_competition(self, catalog, **kwargs):
            return [{"participant_count": 8, "notice_published_date": date(2026, 3, 1),
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "purchase_items": None, "work_type": "service"}]

        def peer_field_market(self, catalog, **kwargs):
            contracts = []
            for organization, multiplier in (("ORG", 1), ("PEER", 2)):
                for index in range(10):
                    contracts.append({"organization_code": organization,
                        "event_key": f"{organization}-{index}",
                        "first_contract_date": date(2026, 1, index + 1),
                        "company_number": f"{multiplier}{index % 5:09d}",
                        "company_name": f"업체 {index % 5}",
                        "attributed_contract_amount": Decimal("500") if organization == "ORG" else Decimal("250"),
                        "amount_completeness": "complete"})
            competition = [
                {"organization_code": organization,
                 "competition_event_id": f"{organization}-{index}",
                 "participant_count": count}
                for organization, count in (("ORG", 8), ("PEER", 4))
                for index in range(5)
            ]
            return contracts, competition

    result = await execute_bid_participation_context(
        RegistryLoader(REGISTRIES).load(), "analyze_bid_participation_context",
        {"bid_notice_id": "CURRENT:000", "period_years": 3}, reader=Reader())
    assert result.outcome["analysis_basis"]["period_to"] == date(2026, 6, 30)
    assert result.outcome["market_entry"]["new_supplier_company_count"] == 1
    assert result.outcome["supplier_concentration"]["top_1_share"] == 0.2
    assert result.outcome["project_scale"]["current_project_amount_basis"] == "allocated_budget"
    assert result.outcome["competition"]["overall_average_participant_count"] == 8
    assert result.outcome["related_past_projects"][0]["relationship_type"] == "same_field"
    benchmark = result.outcome["peer_benchmark"]
    assert benchmark["supplier_concentration"]["minimum_sample_satisfied"] is True
    assert benchmark["supplier_concentration"]["percentile_method"] == "midrank"
    assert benchmark["supplier_concentration"]["current_value"] == result.outcome["supplier_concentration"]["top_5_share"]
    assert benchmark["competition"]["participant_count_median"]["current_value"] == 8
    cases = result.outcome["new_supplier_similar_amount_cases"]
    assert cases["amount_range"]["minimum_amount"] == 500
    assert cases["amount_range"]["maximum_amount"] == 2000
    assert cases["case_unit"] == "contract_event"
    assert result.outcome["reconciliation"]["amount_difference"] == 0


@pytest.mark.asyncio
async def test_rolling_supplier_entry_ignores_start_year_and_filters_history() -> None:
    class Reader:
        history_calls = []

        def activities(self, catalog, **kwargs):
            return [{
                "activity_type": "contract", "event_key": "C-1",
                "bid_notice_id": "C:000", "notice_name": "정보시스템 계약",
                "organization_code": "ORG-1", "organization_name": "기관",
                "company_number": "3333333333", "company_name": "계약업체",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service", "activity_date": date(2025, 4, 1),
                "event_amount": Decimal("100"),
                "attributed_contract_amount": Decimal("100"),
                "amount_completeness": "complete",
            }]

        def organization_award_history(self, catalog, **kwargs):
            self.history_calls.append(kwargs)
            return {"3333333333": date(2025, 4, 1)}, kwargs["history_from"]

    reader = Reader()
    catalog = RegistryLoader(REGISTRIES).load()
    outcomes = []
    supplier_outcomes = []
    for from_year in (2021, 2024):
        result = await execute_organization_procurement_profile(
            catalog, "analyze_organization_procurement_profile", {
                "organization_code": "ORG-1", "period_from_year": from_year,
                "period_to_year": 2025, "work_type": "service",
                "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발", "field_code": "81111599",
            }, reader=reader,
        )
        outcomes.append(result.outcome["summary"]["rolling_12m_supplier_entry"])
        supplier_outcomes.append(result.outcome["supplier_entry"])

    assert outcomes[0] == outcomes[1]
    assert supplier_outcomes[0] == supplier_outcomes[1]
    assert outcomes[0]["history_from"] == date(2020, 1, 1)
    assert outcomes[0]["history_to"] == date(2024, 12, 31)
    for call in reader.history_calls:
        assert call["history_from"] == date(2020, 1, 1)
        assert call["history_to"] == date(2026, 1, 1)
        assert call["work_type"] == "service"
        assert call["large_category"] == "ICT 서비스"
        assert call["middle_category"] == "SW 및 시스템 개발"
        assert call["field_code"] == "81111599"


@pytest.mark.asyncio
async def test_organization_profile_reports_rolling_supplier_entry_without_participation() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            base = {
                "notice_name": "정보시스템 용역",
                "organization_code": "ORG-1", "organization_name": "기관",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "work_type": "service", "event_amount": Decimal("100"),
                "attributed_contract_amount": None, "amount_completeness": "unknown",
            }
            return [
                {**base, "activity_type": "participation", "event_key": "P1",
                 "bid_notice_id": "P1:000", "company_number": "9999999999",
                 "company_name": "참여업체", "activity_date": date(2025, 1, 1)},
                {**base, "activity_type": "award", "event_key": "A1",
                 "bid_notice_id": "A1:000", "company_number": "1111111111",
                 "company_name": "기존업체", "activity_date": date(2025, 2, 1)},
                {**base, "activity_type": "contract", "event_key": "C1",
                 "bid_notice_id": "A1:000", "company_number": "3333333333",
                 "company_name": "공동수급구성원", "activity_date": date(2026, 2, 10),
                 "attributed_contract_amount": Decimal("30"),
                 "amount_completeness": "complete"},
                {**base, "activity_type": "award", "event_key": "A2",
                 "bid_notice_id": "A2:000", "company_number": "2222222222",
                 "company_name": "신규업체", "activity_date": date(2025, 3, 1)},
                {**base, "activity_type": "award", "event_key": "A3",
                 "bid_notice_id": "A3:000", "company_number": None,
                 "company_name": None, "activity_date": date(2025, 4, 1)},
            ]

        def organization_award_history(self, catalog, **kwargs):
            return {
                "1111111111": date(2022, 1, 1),
                "2222222222": date(2025, 3, 1),
                "3333333333": date(2026, 2, 10),
            }, date(2022, 1, 1)

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "period_years": 5}, reader=Reader(),
    )

    assert result.outcome["summary"]["rolling_12m_supplier_entry"] == {
        "window_months": 12,
        "period_from": date.today().replace(year=date.today().year - 1),
        "period_to": date.today(),
        "comparison_period_from": date.today().replace(year=date.today().year - 2),
        "comparison_period_to": date.today().replace(year=date.today().year - 1),
        "first_observed_company_count": 1,
        "reentering_company_count": 0,
        "incumbent_company_count": 0,
        "total_company_count": 1,
        "classified_company_count": 1,
        "first_observed_company_rate": 1.0,
        "entry_and_reentry_rate": 1.0,
        "history_from": date(2022, 1, 1),
        "history_to": date.today().replace(year=date.today().year - 1) - timedelta(days=1),
        "history_years": 5,
        "history_basis": "five_fiscal_years_before_target_period",
        "minimum_sample_size": 10,
        "sample_sufficient": False,
    }


@pytest.mark.asyncio
async def test_bid_relationship_context_batches_only_history_before_notice() -> None:
    class Reader:
        observed_period_to = None

        def bid_context(self, catalog, **kwargs):
            return ({
                "notice_name": "현재 공고", "organization_code": "ORG-1",
                "organization_name": "기관", "notice_published_date": date(2026, 4, 1),
            }, [{
                "company_number": "1111111111", "company_name": "업체",
                "opening_rank": 1, "bid_amount": Decimal("90"), "bid_rate": Decimal("90"),
                "award_date": date(2026, 5, 1), "winning_amount": Decimal("90"),
                "winning_rate": Decimal("90"), "contract_date": None,
                "contract_amount": None, "attributed_contract_amount": None,
                "share_percent": None, "company_role": None,
                "amount_completeness": None,
            }])

        def activities(self, catalog, **kwargs):
            self.observed_period_to = kwargs["period_to"]
            return []

    reader = Reader()
    result = await execute_bid_notice_relationship_context(
        RegistryLoader(REGISTRIES).load(), "get_bid_notice_relationship_context",
        {"bid_notice_id": "N2:000", "relationship_history_years": 5}, reader=reader,
    )

    assert reader.observed_period_to == date(2026, 4, 1)
    assert result.outcome["analysis_basis"]["period_from"] == date(2022, 1, 1)
    assert result.outcome["analysis_basis"]["period_type"] == "calendar_fiscal_years"
    assert result.outcome["participants"][0]["result"] == "awarded"
    assert result.outcome["participants"][0]["prior_organization_relationship"][
        "award_event_count"
    ] == 0


@pytest.mark.asyncio
async def test_construction_profile_uses_official_field_as_flat_category() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            return [{
                "activity_type": "contract", "event_key": "C1",
                "bid_notice_id": "N1:000", "notice_name": "청사 내부 공사",
                "organization_code": "ORG-1", "organization_name": "기관",
                "company_number": "1111111111", "company_name": "업체",
                "procurement_classification_number": "72153699",
                "procurement_classification_name": "실내건축공사",
                "procurement_large_classification_name": None,
                "procurement_middle_classification_name": None,
                "purchase_items": None, "work_type": "construction",
                "activity_date": date(2025, 3, 1), "event_amount": Decimal("100"),
                "attributed_contract_amount": Decimal("100"),
                "amount_completeness": "complete",
            }]

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {
            "organization_code": "ORG-1", "work_type": "construction",
            "large_category": "실내건축공사",
        },
        reader=Reader(),
    )

    assert result.outcome["field_distribution_level"] == "construction_field"
    assert result.outcome["field_hierarchy_depth"] == 1
    assert result.outcome["field_distribution"] == [{
        "field_code": "72153699", "field_name": "실내건축공사",
        "large_category": "실내건축공사", "middle_category": None,
        "detailed_items": [], "classification_source": "construction_work_category",
            "work_types": ["construction"], "participation_count": 0,
            "result_confirmed_participation_count": 0,
            "successful_participation_count": 0, "award_success_rate": None,
        "award_event_count": 0, "contract_event_count": 1, "event_count": 1,
        "attributed_contract_amount": 100, "amount_share": 1.0,
        "display_level": "field_code", "display_code": "72153699",
        "display_name": "실내건축공사", "has_children": False,
        "selection_filter": {
            "work_type": "construction", "large_category": "실내건축공사",
            "field_code": "72153699",
        },
    }]


@pytest.mark.asyncio
async def test_goods_profile_uses_primary_official_purchase_item() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            return [{
                "activity_type": "contract", "event_key": "C1",
                "bid_notice_id": "N1:000", "notice_name": "장비 구매",
                "organization_code": "ORG-1", "organization_name": "기관",
                "company_number": "1111111111", "company_name": "업체",
                "procurement_classification_number": None,
                "procurement_classification_name": None,
                "procurement_large_classification_name": None,
                "procurement_middle_classification_name": None,
                "purchase_items": [
                    {"sequence": "2", "code": "4711150301", "name": "세탁물건조기"},
                    {"sequence": "1", "code": "4711150201", "name": "업소용세탁기"},
                ],
                "work_type": "goods", "activity_date": date(2025, 3, 1),
                "event_amount": Decimal("100"),
                "attributed_contract_amount": Decimal("100"),
                "amount_completeness": "complete",
            }]

    catalog = RegistryLoader(REGISTRIES).load()
    result = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "work_type": "goods"}, reader=Reader(),
    )

    assert result.outcome["field_distribution_level"] == "field"
    assert result.outcome["field_distribution"] == [{
        "field_code": "4711150201", "field_name": "업소용세탁기",
        "large_category": "업소용세탁기", "middle_category": None,
        "detailed_items": [
            {"sequence": "2", "code": "4711150301", "name": "세탁물건조기"},
            {"sequence": "1", "code": "4711150201", "name": "업소용세탁기"},
        ],
        "classification_source": "purchase_item", "work_types": ["goods"],
        "participation_count": 0, "award_event_count": 0,
        "result_confirmed_participation_count": 0,
        "successful_participation_count": 0, "contract_event_count": 1,
        "event_count": 1, "attributed_contract_amount": 100,
        "amount_share": 1.0, "award_success_rate": None,
        "display_level": "field_code", "display_code": "4711150201",
        "display_name": "업소용세탁기", "has_children": False,
        "selection_filter": {
            "work_type": "goods", "large_category": "업소용세탁기",
            "field_code": "4711150201",
        },
    }]

    mixed = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1"}, reader=Reader(),
    )
    assert mixed.outcome["field_distribution_level"] == "large"
    assert mixed.outcome["field_distribution"] == [{
        "large_category": "업소용세탁기", "event_count": 1,
        "participation_count": 0, "award_event_count": 0,
        "result_confirmed_participation_count": 0,
        "successful_participation_count": 0, "award_success_rate": None,
        "contract_event_count": 1, "attributed_contract_amount": 100,
        "work_types": ["goods"], "amount_share": 1.0,
        "display_level": "large_category", "display_code": "업소용세탁기",
        "display_name": "업소용세탁기", "has_children": True,
        "selection_filter": {
            "work_type": "goods", "large_category": "업소용세탁기",
        },
    }]


@pytest.mark.asyncio
async def test_profile_includes_and_filters_unclassified_field_bucket() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            base = {
                "activity_type": "contract", "organization_code": "ORG-1",
                "organization_name": "기관", "company_number": "1111111111",
                "company_name": "업체", "work_type": "goods",
                "activity_date": date(2025, 1, 1), "amount_completeness": "complete",
            }
            return [
                {**base, "event_key": "C1", "bid_notice_id": "N1:000",
                 "notice_name": "분류 물품", "event_amount": Decimal("20"),
                 "attributed_contract_amount": Decimal("20"),
                 "procurement_classification_number": "82141502",
                 "procurement_classification_name": "그래픽디자인서비스",
                 "procurement_large_classification_name": "매체제작·디자인",
                 "procurement_middle_classification_name": "디자인"},
                {**base, "event_key": "C2", "bid_notice_id": "N2:000",
                 "notice_name": "원천 분류 없는 물품", "event_amount": Decimal("80"),
                 "attributed_contract_amount": Decimal("80"),
                 "procurement_classification_number": None,
                 "procurement_classification_name": None,
                 "procurement_large_classification_name": None,
                 "procurement_middle_classification_name": None},
            ]

        def organization_award_history(self, catalog, **kwargs):
            return {}, None

    catalog = RegistryLoader(REGISTRIES).load()
    result = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "work_type": "goods"}, reader=Reader(),
    )
    distribution = {item["large_category"]: item for item in result.outcome[
        "field_distribution"
    ]}
    assert result.outcome["summary"]["total_attributed_contract_amount"] == 100
    assert sum(item["attributed_contract_amount"] for item in distribution.values()) == 100
    assert distribution["미분류"] == {
        "large_category": "미분류", "field_code": None, "field_name": None,
        "middle_category": None, "detailed_items": [],
        "classification_source": "unclassified",
            "event_count": 1, "participation_count": 0, "award_event_count": 0,
            "result_confirmed_participation_count": 0,
            "successful_participation_count": 0, "award_success_rate": None,
        "contract_event_count": 1, "attributed_contract_amount": 80,
        "work_types": ["goods"], "amount_share": 0.8,
        "display_level": "unclassified", "display_code": None,
        "display_name": "미분류", "has_children": False,
        "selection_filter": {"work_type": "goods", "large_category": "미분류"},
    }

    filtered = await execute_organization_procurement_profile(
        catalog, "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "work_type": "goods",
         "large_category": "미분류"}, reader=Reader(),
    )
    assert filtered.outcome["summary"]["total_attributed_contract_amount"] == 80
    assert filtered.outcome["field_distribution_level"] == "unclassified"
    assert filtered.outcome["field_distribution"][0]["classification_source"] == "unclassified"


@pytest.mark.asyncio
async def test_profile_splits_unclassified_buckets_by_work_type() -> None:
    class Reader:
        def activities(self, catalog, **kwargs):
            return [{
                "activity_type": "contract", "event_key": f"C{index}",
                "bid_notice_id": f"N{index}:000", "notice_name": "미분류 계약",
                "organization_code": "ORG-1", "organization_name": "기관",
                "company_number": f"111111111{index}", "company_name": f"업체{index}",
                "work_type": work_type, "activity_date": date(2025, 1, index),
                "event_amount": Decimal(str(amount)),
                "attributed_contract_amount": Decimal(str(amount)),
                "amount_completeness": "complete",
                "procurement_classification_number": None,
                "procurement_classification_name": None,
                "procurement_large_classification_name": None,
                "procurement_middle_classification_name": None,
            } for index, (work_type, amount) in enumerate(
                (("goods", 30), ("service", 70)), start=1,
            )]

        def organization_award_history(self, catalog, **kwargs):
            return {}, None

    result = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1"}, reader=Reader(),
    )
    buckets = sorted(
        (item for item in result.outcome["field_distribution"]
         if item["large_category"] == "미분류"),
        key=lambda item: item["work_types"],
    )
    assert [(item["work_types"], item["attributed_contract_amount"]) for item in buckets] == [
        (["goods"], 30), (["service"], 70),
    ]

    filtered = await execute_organization_procurement_profile(
        RegistryLoader(REGISTRIES).load(), "analyze_organization_procurement_profile",
        {"organization_code": "ORG-1", "large_category": "미분류"}, reader=Reader(),
    )
    assert len(filtered.outcome["field_distribution"]) == 2
