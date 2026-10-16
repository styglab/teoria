from dataclasses import replace
from datetime import date
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.execution.tasks import update_checkpoint


async def test_checkpoint_preserves_domain_counts_and_summary_type():
    summary = LoadSummary(raw_records=2, contracts=3, notices=5, notice_outcomes=7)
    store = Mock(update_checkpoint=AsyncMock())
    execution_id = uuid4()
    cursor = date(2026, 10, 16)
    with patch("teoria_pipelines.execution.tasks._store", return_value=store):
        result = await update_checkpoint.fn(execution_id, "test", cursor, 11, summary)
    assert result == replace(summary, raw_records=11)
    assert type(result) is type(summary)
    assert summary.raw_records == 2
    store.update_checkpoint.assert_called_once_with("test", cursor, execution_id)
