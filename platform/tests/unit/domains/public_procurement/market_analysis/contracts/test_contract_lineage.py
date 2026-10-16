from datetime import date
from pathlib import Path

from teoria.domains.public_procurement.market_analysis.contracts.contract_lineage import (
    _contract_family_summary,
    _decorate_contract_lineage,
)

REGISTRIES = Path(__file__).parents[6] / "registries"


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

