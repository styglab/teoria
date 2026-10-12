from datetime import date
from unittest.mock import Mock

import pytest

from teoria_pipelines.domains.public_procurement.contracts import flows
from teoria_pipelines.models import CollectionWindow, ExtractedBatch, LoadSummary, NormalizedBatch


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_step", ["save_raw_records", "upsert_contracts"])
async def test_failed_storage_does_not_advance_checkpoint_or_complete_run(monkeypatch, failed_step):
    class Extract:
        def with_options(self, **options):
            return self

        async def __call__(self, execution_id, window, *args):
            return ExtractedBatch(execution_id=execution_id, window=window)

    monkeypatch.setattr(flows, "extract_contract_operation", Extract())
    monkeypatch.setattr(flows, "start_pipeline_run", lambda execution_id, *args: execution_id)
    monkeypatch.setattr(flows, "save_raw_records", Mock(return_value=0))
    monkeypatch.setattr(flows, "normalize_contracts", Mock(return_value=NormalizedBatch()))
    monkeypatch.setattr(flows, "upsert_contracts", Mock(return_value=LoadSummary()))
    monkeypatch.setattr(flows, failed_step, Mock(side_effect=RuntimeError("storage unavailable")))
    checkpoint = Mock()
    completed = Mock()
    failed = Mock()
    monkeypatch.setattr(flows, "update_checkpoint", checkpoint)
    monkeypatch.setattr(flows, "complete_pipeline_run", completed)
    monkeypatch.setattr(flows, "fail_pipeline_run", failed)

    with pytest.raises(RuntimeError, match="storage unavailable"):
        await flows.sync_pps_contract_window.fn(CollectionWindow(date(2026, 7, 1), date(2026, 7, 1)))
    checkpoint.assert_not_called()
    completed.assert_not_called()
    failed.assert_called_once()
    assert failed.call_args.args[1] == "RuntimeError"
