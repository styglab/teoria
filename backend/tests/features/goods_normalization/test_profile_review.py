from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from teoria.features.goods_normalization.profiles.service import (
    NormalizationProfileService,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,digest", [("in_review", "b" * 64), ("draft", "a" * 64)]
)
async def test_review_precondition_is_checked_under_row_lock_before_approval(
    status, digest
):
    conn = object()

    @asynccontextmanager
    async def transaction():
        yield conn

    repo = AsyncMock()
    repo.transaction = transaction
    repo.get.return_value = {"status": status, "content_checksum": digest}
    service = NormalizationProfileService(
        repository=repo, ontology_authoring=AsyncMock()
    )
    with pytest.raises(ValueError, match="changed since review"):
        await service.transition(
            UUID(int=1),
            action="approve",
            actor="reviewer",
            expected_status="in_review",
            expected_content_checksum="a" * 64,
        )
    repo.get.assert_awaited_once_with(conn, UUID(int=1), lock=True)
    repo.set_status.assert_not_called()
    repo.record_event.assert_not_called()
