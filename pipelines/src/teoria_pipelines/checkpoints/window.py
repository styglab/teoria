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
