from datetime import date

import pytest

from teoria_pipelines.checkpoints import resolve_collection_window, split_windows
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
