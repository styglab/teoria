from datetime import date

import pytest

from teoria_pipelines.checkpoints import (
    resolve_backfill_windows,
    resolve_collection_window,
    resolve_incremental_window,
    split_windows,
)
from teoria_pipelines.models import CollectionWindow


def test_checkpoint_overlap_and_daily_windows() -> None:
    window = resolve_collection_window(
        requested_start=None,
        requested_end=date(2026, 7, 31),
        checkpoint=date(2026, 7, 30),
        overlap_days=2,
    )

    assert window == CollectionWindow(date(2026, 7, 28), date(2026, 7, 31))
    assert split_windows(window, 1) == [
        CollectionWindow(date(2026, 7, 28), date(2026, 7, 28)),
        CollectionWindow(date(2026, 7, 29), date(2026, 7, 29)),
        CollectionWindow(date(2026, 7, 30), date(2026, 7, 30)),
        CollectionWindow(date(2026, 7, 31), date(2026, 7, 31)),
    ]


def test_first_run_requires_explicit_start_date() -> None:
    with pytest.raises(ValueError, match="start_date"):
        resolve_collection_window(
            requested_start=None,
            requested_end=date(2026, 7, 31),
            checkpoint=None,
            overlap_days=2,
        )


def test_incremental_window_always_refreshes_recent_days() -> None:
    assert resolve_incremental_window(
        lookback_days=3,
        today=date(2026, 8, 1),
    ) == CollectionWindow(date(2026, 7, 30), date(2026, 8, 1))


def test_backfill_moves_forward_in_bounded_batches() -> None:
    assert resolve_backfill_windows(
        start_date=date(2025, 1, 1),
        end_date=date(2026, 7, 31),
        checkpoint=None,
        batch_days=3,
        today=date(2026, 8, 1),
    ) == [
        CollectionWindow(date(2025, 1, 1), date(2025, 1, 1)),
        CollectionWindow(date(2025, 1, 2), date(2025, 1, 2)),
        CollectionWindow(date(2025, 1, 3), date(2025, 1, 3)),
    ]

    assert resolve_backfill_windows(
        start_date=date(2025, 1, 1),
        end_date=date(2026, 7, 31),
        checkpoint=date(2025, 1, 3),
        batch_days=2,
        today=date(2026, 8, 1),
    ) == [
        CollectionWindow(date(2025, 1, 4), date(2025, 1, 4)),
        CollectionWindow(date(2025, 1, 5), date(2025, 1, 5)),
    ]


def test_completed_backfill_does_not_repeat_the_finished_range() -> None:
    assert resolve_backfill_windows(
        start_date=date(2025, 1, 1),
        end_date=date(2026, 7, 31),
        checkpoint=date(2026, 7, 31),
        batch_days=1,
        today=date(2026, 8, 1),
    ) == []


def test_backfill_rejects_a_non_historical_end_date() -> None:
    with pytest.raises(ValueError, match="end_date"):
        resolve_backfill_windows(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 1),
            checkpoint=None,
            batch_days=30,
            today=date(2026, 8, 1),
        )
