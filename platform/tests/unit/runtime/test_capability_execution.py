import asyncio
from datetime import date
from pathlib import Path

import pytest

from teoria.runtime.capability import CapabilityBinder, CapabilityExecutionError, CapabilityRunner
from teoria_provider.models import ExecutionResponse
from teoria.registry.loader import RegistryLoader


ROOT = Path(__file__).parents[3]


class FakeExecutor:
    def __init__(self, responses: list[ExecutionResponse]) -> None:
        self.responses = list(responses)
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


class PaginatedProfileExecutor:
    def __init__(self) -> None:
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        page = request.query["pageNo"]
        count = 10 if page == 1 else 1
        telephone = "02-0000-0000" if page == 1 else "02-1111-1111"
        opened = "20250101" if page == 1 else "20260101"
        items = [
            {
                "crno": "1301110006246",
                "corpNm": "테스트법인",
                "bzno": "0000000000",
                "enpBsadr": "서울특별시 중구",
                "enpDtadr": "1층",
                "enpTlno": telephone,
                "lastOpegDt": opened,
            }
            for _ in range(count)
        ]
        return response(
            {
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                    "body": {"numOfRows": 10, "pageNo": page, "totalCount": 11, "items": {"item": items}},
                }
            }
        )


def response(body: dict) -> ExecutionResponse:
    return ExecutionResponse(
        status_code=200,
        content_type="application/json",
        headers={},
        body=body,
        elapsed_ms=1.0,
    )


def html_records(records: list[dict]) -> ExecutionResponse:
    return ExecutionResponse(
        status_code=200,
        content_type="text/html",
        headers={},
        body={"records": records},
        elapsed_ms=1.0,
    )


def test_binds_composite_verification_input_to_source_request() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    capability = catalog.capabilities["verify_business_registration"]

    bound = CapabilityBinder().bind(
        catalog,
        capability,
        capability.steps[0],
        {
            "businesses": [
                {
                    "business_registration_number": "0000000000",
                    "opened_date": date(2020, 1, 2),
                    "representative_name": "홍길동",
                    "business_name": "테스트상사",
                },
                {
                    "business_registration_number": "1111111111",
                    "opened_date": date(2021, 3, 4),
                    "representative_name": "김테스트",
                },
            ]
        },
    )

    assert bound == {
        "body": {
            "businesses": [
                {"b_no": "0000000000", "start_dt": "20200102", "p_nm": "홍길동", "b_nm": "테스트상사"},
                {"b_no": "1111111111", "start_dt": "20210304", "p_nm": "김테스트"},
            ]
        }
    }


@pytest.mark.asyncio
async def test_runs_capability_and_decodes_ontology_objects() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    executor = FakeExecutor(
        [
            response(
                {
                    "status_code": "OK",
                    "request_cnt": 1,
                    "match_cnt": 1,
                    "data": [
                        {
                            "b_no": "0000000000",
                            "b_stt": "계속사업자",
                            "b_stt_cd": "01",
                            "tax_type": "부가가치세 일반과세자",
                            "tax_type_cd": "01",
                            "end_dt": "",
                            "utcc_yn": "N",
                            "tax_type_change_dt": "",
                            "invoice_apply_dt": "",
                            "rbf_tax_type": "해당없음",
                            "rbf_tax_type_cd": "99",
                        }
                    ]
                }
            )
        ]
    )

    result = await CapabilityRunner(executor).run(
        catalog,
        "get_business_registration_status",
        {"business_registration_numbers": ["0000000000"]},
    )

    assert executor.requests[0].body == {"b_no": ["0000000000"]}
    objects = {item.object_type: item.properties for item in result.objects}
    assert objects["business_registration"]["business_registration_number"] == "0000000000"
    status = objects["taxpayer_status_observation"]
    assert status["operating_status"] == "active"
    assert status["current_taxation_type"] == "general_taxpayer"
    assert status["previous_taxation_type"] == "not_applicable"
    assert status["is_closed_due_to_unit_tax_conversion"] is False
    assert status["observation_id"]
    assert status["observed_at"]
    status_object = next(item for item in result.objects if item.object_type == "taxpayer_status_observation")
    assert status_object.property_provenance["operating_status"][0].kind == "source"
    assert status_object.property_provenance["operating_status"][0].source == "nts_business_registration"
    assert status_object.property_provenance["observation_id"][0].kind == "execution"
    assert status_object.property_provenance["observed_at"][0].operation == "materialize"
    assert len(result.links) == 1
    assert result.links[0].link_type == "business_registration_has_taxpayer_status"
    assert result.responses is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("records", "expected_status", "expected_match"),
    [
        ([{"vnia_sn": 1, "cmp_nm": "테스트벤처", "rprsv_nm": "대표자", "bizrno": "0000000000", "hdofc_addr": "서울특별시", "indsty_cd": "62", "indsty_nm": "정보통신업"}], "currently_disclosed", True),
        ([], "not_disclosed", False),
    ],
)
async def test_verifies_current_venture_company_disclosure(
    records: list[dict], expected_status: str, expected_match: bool
) -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    executor = FakeExecutor([response({"RESULT": "SUCCESS", "TOTAL_COUNT": str(len(records)), "NOW_PAGE": "1", "DATA_LIST": records})])

    result = await CapabilityRunner(executor).run(
        catalog,
        "verify_venture_company",
        {"business_registration_number": "0000000000"},
    )

    assert executor.requests[0].body["bizRNo"] == "0000000000"
    assert result.outcome["status"] == expected_status
    assert result.outcome["matched"] is expected_match
    if expected_match:
        objects = {item.object_type: item for item in result.objects}
        disclosure = objects["venture_company_disclosure"].properties
        assert disclosure["status"] == "currently_disclosed"
        assert disclosure["observed_at"]
        assert any(
            item.link_type == "business_registration_has_venture_company_disclosure"
            for item in result.links
        )
    else:
        assert result.objects == []
        assert result.links == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capability_id", "query_field", "record", "expected_match"),
    [
        (
            "verify_innobiz_company",
            "Co_Name",
            {
                "company_name": "테스트이노비즈",
                "representative_name": "대표자",
                "region": "서울",
                "industry": "정보통신 (SW)",
                "certification_period": "2026-01-01 ~ 2026-12-31",
            },
            True,
        ),
        (
            "verify_mainbiz_company",
            "certiCheck",
            {
                "company_name": "테스트메인비즈",
                "region": "경기",
                "certification_period": "2025-01-01 ~ 2025-12-31",
                "renewal_period": "2025-10-01 ~ 2026-01-31",
            },
            False,
        ),
    ],
)
async def test_verifies_innovation_certification_validity(
    capability_id: str, query_field: str, record: dict, expected_match: bool
) -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    executor = FakeExecutor([html_records([record])])

    result = await CapabilityRunner(executor).run(
        catalog,
        capability_id,
        {"business_registration_number": "0000000000"},
    )

    assert executor.requests[0].query[query_field] == "0000000000"
    assert result.outcome["matched"] is expected_match
    assert result.outcome["status"] == (
        "currently_certified" if expected_match else "not_currently_certified"
    )
    objects = {item.object_type: item for item in result.objects}
    assert objects["business_registration"].properties["business_registration_number"] == "0000000000"
    certification = objects["innovation_certification_observation"].properties
    assert certification["valid_from"] == date.fromisoformat(record["certification_period"].split(" ~ ")[0])
    assert certification["valid_until"] == date.fromisoformat(record["certification_period"].split(" ~ ")[1])
    assert any(
        item.link_type == "business_registration_has_innovation_certification"
        for item in result.links
    )


@pytest.mark.asyncio
async def test_paginates_merges_latest_record_and_materializes_links() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    executor = PaginatedProfileExecutor()

    result = await CapabilityRunner(executor).run(
        catalog,
        "get_company_profile",
        {"corporate_registration_number": "1301110006246"},
    )

    assert [request.query["pageNo"] for request in executor.requests] == [1, 2]
    by_type = {}
    for item in result.objects:
        by_type.setdefault(item.object_type, []).append(item)
    assert {key: len(value) for key, value in by_type.items()} == {
        "legal_entity": 1,
        "business_registration": 1,
        "postal_address": 1,
    }
    assert by_type["legal_entity"][0].properties["telephone_number"] == "02-1111-1111"
    assert by_type["postal_address"][0].properties["address_id"]
    assert {link.link_type for link in result.links} == {
        "legal_entity_has_address",
        "legal_entity_has_business_registration",
    }


@pytest.mark.asyncio
async def test_stops_pagination_at_configured_page_limit() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    executor = PaginatedProfileExecutor()

    with pytest.raises(CapabilityExecutionError) as exc_info:
        await CapabilityRunner(executor, max_pages=1).run(
            catalog,
            "get_company_profile",
            {"corporate_registration_number": "1301110006246"},
        )

    assert exc_info.value.code == "source_page_limit_exceeded"
    assert exc_info.value.page == 2
    assert len(executor.requests) == 1


@pytest.mark.asyncio
async def test_stops_capability_at_configured_deadline() -> None:
    class SlowExecutor:
        async def execute(self, request):
            await asyncio.sleep(0.05)

    catalog = RegistryLoader(ROOT / "registries").load()
    with pytest.raises(CapabilityExecutionError) as exc_info:
        await CapabilityRunner(SlowExecutor(), timeout_seconds=0.001).run(
            catalog,
            "get_company_profile",
            {"corporate_registration_number": "1301110006246"},
        )

    assert exc_info.value.code == "capability_timeout"
    assert exc_info.value.retryable is True
