from datetime import date, timedelta

from teoria_pipelines.models import CollectionWindow


def resolve_collection_window(*, requested_start: date | None, requested_end: date | None,
                              checkpoint: date | None, overlap_days: int,
                              today: date | None = None) -> CollectionWindow:
    end = requested_end or today or date.today()
    if requested_start is not None:
        start = requested_start
    elif checkpoint is not None:
        start = checkpoint - timedelta(days=overlap_days)
    else:
        raise ValueError("start_date is required when no checkpoint exists")
    return CollectionWindow(start=start, end=end)


def split_windows(window: CollectionWindow, window_days: int) -> list[CollectionWindow]:
    if window_days < 1:
        raise ValueError("window_days must be at least 1")
    result: list[CollectionWindow] = []
    current = window.start
    while current <= window.end:
        end = min(current + timedelta(days=window_days - 1), window.end)
        result.append(CollectionWindow(current, end))
        current = end + timedelta(days=1)
    return result


def resolve_incremental_window(*, lookback_days: int,
                               today: date | None = None) -> CollectionWindow:
    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")
    current = today or date.today()
    return CollectionWindow(
        start=current - timedelta(days=lookback_days - 1),
        end=current,
    )


def resolve_backfill_windows(*, start_date: date, checkpoint: date | None,
                             end_date: date, batch_days: int,
                             today: date | None = None) -> list[CollectionWindow]:
    """Return the next batch of daily windows in chronological order."""

    if batch_days < 1:
        raise ValueError("batch_days must be at least 1")
    current = today or date.today()
    if end_date >= current:
        raise ValueError("backfill end_date must precede today")
    target_end = end_date
    lower = start_date if checkpoint is None else max(start_date, checkpoint + timedelta(days=1))
    if lower > target_end:
        return []
    upper = min(target_end, lower + timedelta(days=batch_days - 1))
    return split_windows(CollectionWindow(lower, upper), 1)
