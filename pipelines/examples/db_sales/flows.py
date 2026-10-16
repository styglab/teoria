"""Previous day's PostgreSQL changes -> transform -> validate -> warehouse UPSERT."""

import asyncio

from datetime import date, datetime, time, timedelta
import os
from zoneinfo import ZoneInfo

import great_expectations as gx
import pandas as pd
from prefect import flow, task
from prefect.runtime import flow_run
from teoria_pipelines.persistence.connection import connect
from psycopg.rows import dict_row


@task(name="처리 날짜 확정", retries=0, persist_result=False)
def resolve_window(business_date: date | None) -> tuple[datetime, datetime]:
    timezone = ZoneInfo("Asia/Seoul")
    if business_date is None:
        # Use the scheduled date, so a delayed Worker still reads the intended day.
        business_date = flow_run.scheduled_start_time.astimezone(
            timezone
        ).date() - timedelta(days=1)
    start = datetime.combine(business_date, time.min, tzinfo=timezone)
    return start, start + timedelta(days=1)


@task(name="Extract: 전날 변경 주문 조회", persist_result=False)
async def extract_orders(window_start: datetime, window_end: datetime) -> list[dict]:
    async with connect(
        os.environ["ETL_SOURCE_DATABASE_URL"],
        row_factory=dict_row,
        connect_timeout=10,
        options="-c statement_timeout=30000 -c default_transaction_read_only=on",
    ) as connection:
        cursor = await connection.execute(
            """SELECT order_id, order_date, amount, status, is_deleted, updated_at
               FROM public.orders
               WHERE updated_at >= %s AND updated_at < %s
               ORDER BY updated_at, order_id""",
            (window_start, window_end),
        )
        return await cursor.fetchall()


@task(name="Transform: 주문 상태 표기 통일", retries=0, persist_result=False)
def transform_orders(orders: list[dict]) -> list[dict]:
    # Keep cancelled and soft-deleted rows: the warehouse must receive those changes too.
    return [
        {
            **row,
            "status": row["status"].strip().lower()
            if isinstance(row["status"], str)
            else row["status"],
        }
        for row in orders
    ]


@task(name="Validate: 적재 전 품질 검사", retries=0, persist_result=False)
def validate_orders(rows: list[dict]) -> None:
    context = gx.get_context(mode="ephemeral")
    context.enable_analytics(False)
    context.variables.progress_bars = {"globally": False}
    source = context.data_sources.add_pandas(name="orders")
    asset = source.add_dataframe_asset(name="changed_orders")
    definition = asset.add_batch_definition_whole_dataframe(name="all_rows")
    batch = definition.get_batch(batch_parameters={"dataframe": pd.DataFrame(rows)})
    checks = [
        gx.expectations.ExpectColumnValuesToNotBeNull(column=column)
        for column in (
            "order_id",
            "order_date",
            "amount",
            "status",
            "is_deleted",
            "updated_at",
        )
    ] + [
        gx.expectations.ExpectColumnValuesToBeUnique(column="order_id"),
        gx.expectations.ExpectColumnValuesToBeBetween(column="amount", min_value=0),
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="status", value_set=["pending", "paid", "cancelled"]
        ),
        gx.expectations.ExpectColumnValuesToBeOfType(column="is_deleted", type_="bool"),
    ]
    for check in checks:
        result = batch.validate(check, result_format="BOOLEAN_ONLY")
        if not result.success:
            # Report the failed rule, without logging row values or connection strings.
            raise ValueError(f"적재 중단: {type(check).__name__} ({check.column})")


@task(name="Load: DW 주문 갱신", persist_result=False)
async def load_orders(rows: list[dict]) -> None:
    # One transaction; soft-deleted rows remain in DW with is_deleted=true.
    async with connect(
        os.environ["ETL_TARGET_DATABASE_URL"],
        connect_timeout=10,
        options="-c statement_timeout=30000 -c lock_timeout=5000",
    ) as connection:
        async with connection.cursor() as cursor:
            await cursor.executemany(
                """INSERT INTO warehouse.orders AS target
                       (order_id, order_date, amount, status, is_deleted, updated_at)
                   VALUES (%(order_id)s, %(order_date)s, %(amount)s,
                           %(status)s, %(is_deleted)s, %(updated_at)s)
                   ON CONFLICT (order_id) DO UPDATE SET
                       order_date = EXCLUDED.order_date, amount = EXCLUDED.amount,
                       status = EXCLUDED.status, is_deleted = EXCLUDED.is_deleted,
                       updated_at = EXCLUDED.updated_at
                   WHERE target.updated_at < EXCLUDED.updated_at""",
                rows,
            )


@flow(
    name="orders-etl",
    retries=0,
    timeout_seconds=300,
    persist_result=False,
    log_prints=True,
)
async def orders_etl(
    business_date: date | None = None,
    db_retries: int = 2,
    db_retry_delay_seconds: int = 5,
    db_task_timeout_seconds: int = 60,
) -> int:
    if db_retries < 0 or db_retry_delay_seconds < 0 or db_task_timeout_seconds <= 0:
        raise ValueError(
            "재시도 횟수·대기 시간은 0 이상, 제한 시간은 0보다 커야 합니다."
        )
    db_policy = dict(
        retries=db_retries,
        retry_delay_seconds=db_retry_delay_seconds,
        timeout_seconds=db_task_timeout_seconds,
    )
    window_start, window_end = resolve_window(business_date)
    print(f"조회 범위: {window_start.isoformat()} 이상, {window_end.isoformat()} 미만")
    orders = await extract_orders.with_options(**db_policy)(window_start, window_end)
    rows = transform_orders(orders)
    if not rows:
        print("변경 주문 0건: 적재할 데이터가 없습니다.")
        return 0
    validate_orders(rows)  # An exception here prevents Load from being called.
    await load_orders.with_options(**db_policy)(rows)
    print(
        f"적재 처리 완료: {window_start.date()}, 입력 {len(rows)}건 (동일·이전 버전은 저장 생략)"
    )
    return len(rows)


if __name__ == "__main__":
    asyncio.run(orders_etl())
