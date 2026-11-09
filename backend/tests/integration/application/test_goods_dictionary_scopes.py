"""Product scope is observed context; reusable definitions keep one identity."""

import os
from pathlib import Path
from uuid import uuid4
import pytest
from teoria.integrations.application_database import apply_migrations
from teoria.domains.goods.expression_links.contracts import (
    DictionarySubmission,
    source_literal_definition,
)
from teoria.domains.goods.expression_links.registration_service import (
    ExpressionRegistrationService,
)
from teoria.domains.goods.expression_links.legacy.meaning_service import (
    LegacyMeaningService,
)
from teoria.domains.goods.expression_links.snapshot_contracts import (
    ConceptDefinition,
    MappingProposal,
    MeaningDecision,
)
from teoria.platform.ontology.bindings.repository import BindingRepository

URL = os.environ.get("TEORIA_TEST_APP_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="isolated Application DB required")


async def test_scoped_catalog_preserves_shared_definitions_and_unmapped_observations():
    await apply_migrations(URL, Path("backend/migrations/application"))
    key = "scope_" + uuid4().hex
    source_name = "검증 물품 " + key
    dictionary = ExpressionRegistrationService(URL)
    meanings = LegacyMeaningService(URL)

    def body(code):
        return DictionarySubmission(
            classification_code=code,
            sources=[
                {
                    "document_id": key,
                    "source_sha256": "a" * 64,
                    "parser_version": "test",
                    "nodes": [{"locator": "row1", "text": source_name}],
                }
            ],
            candidates=[
                {
                    "candidate_key": "item",
                    "kind": "item_type",
                    "preferred_name": source_name,
                    "definition": source_literal_definition("item_type", source_name),
                    "origin_ref": "item1",
                    "evidence": [
                        {
                            "document_id": key,
                            "source_sha256": "a" * 64,
                            "locator": "row1",
                            "quote": source_name,
                        }
                    ],
                }
            ],
        )

    a, b, other = "1111111111", "2222222222", "3333333333"
    first = await dictionary.author(key + "_a", body(a), actor="test:owner")
    second = await dictionary.author(key + "_b", body(b), actor="test:owner")
    assert first["classification_code"] == a and second["classification_code"] == b
    entry = first["decisions"][0]["entry_id"]
    assert second["decisions"][0]["entry_id"] == entry
    for code in [a, b]:
        assert (await meanings.catalog("source", query=key, classification=code))[
            "total"
        ] == 1
        assert (
            await meanings.catalog(
                "source", query=key, classification=code, unresolved=True
            )
        )["total"] == 1
    assert not (await meanings.catalog("source", query=key, classification=other))[
        "items"
    ]
    assert not (
        await meanings.catalog("source", query=key, classification="unclassified")
    )["items"]
    definition = await meanings.propose_concept(
        ConceptDefinition(
            key=key,
            kind="item_type",
            preferred_name="공통 검증 정의",
            definition="여러 품목에서 재사용하는 검증용 물품 정의입니다.",
            references=["synthetic:source"],
        ),
        actor="test:owner",
    )
    await meanings.decide(
        "concept",
        definition["revision_id"],
        MeaningDecision(
            action="approve", rationale="합성 원문과 업무 정의의 적용 범위 검토"
        ),
        actor="test:owner",
    )
    assert not (await meanings.catalog("concept", query=key, classification=a))["items"]
    for code in [a, b]:
        mapping = await meanings.propose_mapping(
            MappingProposal(
                source_entry_id=entry,
                target_revision_id=definition["revision_id"],
                classification_code=code,
                rationale="품목별 원문 근거와 공통 정의의 동일 의미 검토",
            ),
            actor="test:owner",
        )
        assert (
            await meanings.catalog(
                "mapping", classification=code, status="draft", query=key
            )
        )["total"] == 1
        await meanings.decide(
            "mapping",
            mapping["mapping_id"],
            MeaningDecision(
                action="approve", rationale="품목별 적용 문맥과 원문 근거 확인"
            ),
            actor="test:owner",
        )
        page = await meanings.catalog("concept", classification=code, query=key)
        assert [r["concept_id"] for r in page["items"]] == [definition["concept_id"]]
        assert not (
            await meanings.catalog(
                "source", classification=code, query=key, unresolved=True
            )
        )["items"]
    codes = await meanings.classifications(query="111", limit=1)
    assert any(r["classification_code"] == a for r in codes["items"])
    document_scoped = body(None)
    document_scoped.sources[0].classification_code = other
    registered = await dictionary.author(key + "_document_scope", document_scoped, actor="test:owner")
    assert registered["source_classifications"] == {key: other}
    assert (await meanings.catalog("source", query=key, classification=other))["total"] == 1
    assert not (await meanings.catalog("concept", query=key, classification=other))["items"]
    # A historical observation without a code stays unknown, even if its expression is mapped elsewhere.
    await dictionary.author(key + "_legacy", body(None), actor="test:owner")
    assert (
        await meanings.catalog(
            "source", query=key, classification="unclassified", unresolved=True
        )
    )["total"] == 1
    # SQL filters stay parameterized, and namespace/concept scopes reach the DB before LIMIT.
    assert (
        await BindingRepository(URL).list_bindings(
            ontology_namespace="' OR true --", ontology_concept_id=uuid4()
        )
        == []
    )
