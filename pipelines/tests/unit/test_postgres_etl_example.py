"""Exercise daily windows and the quality gate without connecting to a database."""

from datetime import date, datetime, timedelta
from decimal import Decimal
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip(
    "great_expectations", reason="requires the etl-example dependency group"
)

EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "examples/db_sales/flows.py"
spec = importlib.util.spec_from_file_location("postgres_etl_example", EXAMPLE_PATH)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)
KST = ZoneInfo("Asia/Seoul")


def row(**changes):
    return (
        dict(
            order_id="A001",
            order_date=date(2026, 9, 1),
            amount=Decimal("12000"),
            status="paid",
            is_deleted=False,
            updated_at=datetime(2026, 10, 15, 12, tzinfo=KST),
        )
        | changes
    )


def run_without_orchestration(monkeypatch, orders):
    read = AsyncMock(return_value=orders)
    save = AsyncMock()
    monkeypatch.setattr(example, "resolve_window", example.resolve_window.fn)
    monkeypatch.setattr(
        example, "extract_orders", SimpleNamespace(with_options=lambda **_: read)
    )
    monkeypatch.setattr(
        example, "load_orders", SimpleNamespace(with_options=lambda **_: save)
    )
    monkeypatch.setattr(example, "transform_orders", example.transform_orders.fn)
    monkeypatch.setattr(example, "validate_orders", example.validate_orders.fn)
    return read, save


async def test_changes_include_old_orders_cancellations_and_soft_deletes(monkeypatch):
    orders = [
        row(status=" PAID "),
        row(order_id="A002", status="cancelled"),
        row(order_id="A003", is_deleted=True),
    ]
    read, save = run_without_orchestration(monkeypatch, orders)
    assert await example.orders_etl.fn(business_date=date(2026, 10, 15)) == 3
    read.assert_called_once_with(
        datetime(2026, 10, 15, tzinfo=KST), datetime(2026, 10, 16, tzinfo=KST)
    )
    save.assert_called_once_with([row(), orders[1], orders[2]])


@pytest.mark.parametrize(
    "orders",
    [
        [row(amount=-1)],
        [row(amount=None)],
        [row(order_id=None)],
        [row(order_date=None)],
        [row(updated_at=None)],
        [row(is_deleted=None)],
        [row(is_deleted="true")],
        [row(is_deleted=1)],
        [row(status=None)],
        [row(status="unknown")],
        [row(), row()],
    ],
)
async def test_quality_failure_prevents_load(monkeypatch, orders):
    _, save = run_without_orchestration(monkeypatch, orders)
    with pytest.raises(ValueError, match="적재 중단"):
        await example.orders_etl.fn(business_date=date(2026, 10, 15))
    save.assert_not_called()


async def test_no_changes_skips_validation_and_load(monkeypatch):
    _, save = run_without_orchestration(monkeypatch, [])
    validate = Mock(side_effect=AssertionError("empty batches should skip validation"))
    monkeypatch.setattr(example, "validate_orders", validate)
    assert await example.orders_etl.fn(business_date=date(2026, 10, 15)) == 0
    validate.assert_not_called()
    save.assert_not_called()


def test_window_uses_scheduled_korean_date_even_when_execution_is_delayed(monkeypatch):
    # 2026-12-31 15:00 UTC is 2027-01-01 00:00 in Korea.
    monkeypatch.setattr(
        example,
        "flow_run",
        SimpleNamespace(
            scheduled_start_time=datetime(2026, 12, 31, 15, tzinfo=ZoneInfo("UTC")),
        ),
    )
    assert example.resolve_window.fn(None) == (
        datetime(2026, 12, 31, tzinfo=KST),
        datetime(2027, 1, 1, tzinfo=KST),
    )


def test_manual_backfill_uses_requested_date_not_current_schedule(monkeypatch):
    monkeypatch.setattr(
        example,
        "flow_run",
        SimpleNamespace(
            scheduled_start_time=datetime(2026, 10, 16, 22, tzinfo=KST),
        ),
    )
    start, end = example.resolve_window.fn(date(2024, 2, 29))
    assert start == datetime(2024, 2, 29, tzinfo=KST)
    assert end == datetime(2024, 3, 1, tzinfo=KST)
    assert end - start == timedelta(days=1)
