"""Real SQL migration and immutable application-version persistence in an isolated DB."""

import os
from pathlib import Path
from uuid import uuid4
import pytest
from teoria.integrations.application_database import apply_migrations
from teoria.domains.goods.normalization.processing_criteria_repository import (
    ApplicationStandardsRepository,
)
from teoria.domains.goods.expression_links.legacy.meaning_repository import (
    LegacyMeaningRepository,
)
from teoria.domains.goods.expression_links.legacy.meaning_service import (
    LegacyMeaningService,
)

URL = os.environ.get("TEORIA_TEST_APP_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="isolated Application DB required")


async def test_application_version_persists_refs_and_catalog_queries_are_bounded():
    await apply_migrations(URL, Path("backend/migrations/application"))
    repo = ApplicationStandardsRepository(URL)
    id = uuid4()
    body = {
            "release_id": id,
            "name": "Synthetic version",
            "source_run_id": "synthetic_run",
            "classification_code": None,
            "standard_kind": "extraction_draft",
            "standard_ref": {"uri": "s3://test/standard.json", "sha256": "a" * 64},
            "dictionary_ref": {"uri": "s3://test/dictionary.json", "sha256": "b" * 64},
            "dictionary_checksum": "c" * 64,
            "content_checksum": "d" * 64,
            "approved_by": "test:owner",
            "rationale": "Synthetic reference persistence verification",
        }
    row = await repo.create(body)
    replay = await repo.create(body)
    assert replay['release_id'] == row['release_id']
    with pytest.raises(ValueError, match='idempotency_conflict'):
        await repo.create({**body, 'rationale':'Different approval using the same version ID'})
    assert row["status"] == "approved"
    assert (await repo.get(id))["dictionary_ref"]["sha256"] == "b" * 64
    page = await repo.list(0, 1)
    assert len(page["items"]) == 1 and page["total"] >= 1
    meaning = LegacyMeaningService(URL)
    for kind in ("concept", "mapping", "source"):
        page = await meaning.catalog(
            kind, query="' OR true --", status="approved", limit=1
        )
        assert page["items"] == []
