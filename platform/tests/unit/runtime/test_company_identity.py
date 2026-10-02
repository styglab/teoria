from types import SimpleNamespace

import pytest

from teoria.runtime.capability.runner import CapabilityResult
from teoria.runtime.company_identity.processor import execute_company_identifier_resolution
from teoria.runtime.mapping.materializer import MaterializedLink, MaterializedObject


def obj(object_type, identity, **properties):
    return MaterializedObject(
        ontology="company" if object_type != "procurement_supplier" else "public_procurement",
        object_type=object_type,
        object_id=identity,
        properties=properties,
        provenance=[],
        property_provenance={},
    )


def link(source_identity, target_identity):
    return MaterializedLink(
        ontology="company",
        link_type="legal_entity_has_business_registration",
        source_object_id=source_identity,
        target_object_id=target_identity,
        provenance=[],
    )


class NestedRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def _run(self, catalog, capability_id, inputs, *, include_raw_responses):
        self.calls.append((capability_id, inputs))
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_resolves_only_exact_business_number_match():
    registration = obj(
        "business_registration", "registration:1",
        business_registration_number="2148627427",
    )
    entity = obj(
        "legal_entity", "entity:1",
        corporate_registration_number="1101111234567",
        financial_supervisory_unique_number="00123456",
    )
    runner = NestedRunner([
        CapabilityResult(
            capability_id="search_companies_by_name",
            objects=[registration, entity],
            links=[link("entity:1", "registration:1")],
        ),
    ])

    result = await execute_company_identifier_resolution(
        runner, SimpleNamespace(), "resolve_company_identifiers",
        {
            "business_registration_number": "2148627427",
            "company_name": "한국이디에스",
        },
    )

    assert result.outcome["resolution_status"] == "confirmed"
    assert result.outcome["identifiers"]["corporate_registration_number"] == "1101111234567"
    assert [call[0] for call in runner.calls] == ["search_companies_by_name"]


@pytest.mark.asyncio
async def test_does_not_expose_name_only_candidate_as_resolved():
    other_registration = obj(
        "business_registration", "registration:2",
        business_registration_number="9999999999",
    )
    other_entity = obj(
        "legal_entity", "entity:2", corporate_registration_number="1101119999999",
    )
    runner = NestedRunner([
        CapabilityResult(
            capability_id="search_companies_by_name",
            objects=[other_registration, other_entity],
            links=[link("entity:2", "registration:2")],
        ),
    ])

    result = await execute_company_identifier_resolution(
        runner, SimpleNamespace(), "resolve_company_identifiers",
        {
            "business_registration_number": "2148627427",
            "company_name": "동명이인법인",
        },
    )

    assert result.objects == []
    assert result.outcome["resolution_status"] == "unresolved"
    assert result.outcome["warnings"] == ["exact_business_number_match_not_found"]
