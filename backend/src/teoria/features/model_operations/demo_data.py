"""Reproducible synthetic customer data, isolated from production domain tables."""

from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import date, timedelta

from teoria.integrations.data_operations.persistence.connection import connect

DATASET_VERSION = "synthetic_customers_v1"
FEATURES = ["tenure_months", "monthly_spend", "login_days_30d", "support_tickets_30d"]


def generate_customers(count: int = 600) -> tuple[list[tuple], list[tuple]]:
    if not 100 <= count <= 5000:
        raise ValueError("sample count must be between 100 and 5000")
    rng = random.Random(20261027)
    customers, activity = [], []
    for index in range(count):
        identifier = f"SYNTHETIC-{index:05d}"
        customers.append(
            (
                DATASET_VERSION,
                identifier,
                f"가상고객{index:05d}",
                f"customer{index:05d}@example.invalid",
                f"010-XXXX-{index:04d}",
                date(1950, 1, 1) + timedelta(days=rng.randrange(22000)),
                f"가상시 가상구 예제길 {index + 1}",
                rng.randrange(20, 121) * 1000000,
                rng.randrange(350, 1001),
                rng.random() < 0.6,
                True,
            )
        )
        tenure, spend = rng.randrange(1, 73), round(rng.uniform(10, 200), 2)
        logins, tickets = rng.randrange(31), rng.randrange(13)
        score = 0.8 - 0.035 * tenure - 0.15 * logins + 0.40 * tickets
        churned = rng.random() < 1 / (1 + math.exp(-score))
        activity.append(
            (DATASET_VERSION, identifier, tenure, spend, logins, tickets, churned, True)
        )
    return customers, activity


async def seed_customers(database_url: str) -> dict:
    customers, activity = generate_customers()
    async with connect(database_url) as connection:
        # Reruns verify the same immutable dataset instead of replacing existing rows.
        await connection.execute("SELECT pg_advisory_xact_lock(72961027)")
        async with connection.cursor() as cursor:
            await cursor.executemany(
                """INSERT INTO mlops_demo.customers VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                customers,
            )
            await cursor.executemany(
                """INSERT INTO mlops_demo.customer_activity VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                activity,
            )
        for table, expected in (
            ("customers", customers),
            ("customer_activity", activity),
        ):
            rows = await (
                await connection.execute(
                    f"SELECT * FROM mlops_demo.{table} WHERE dataset_version=%s ORDER BY customer_id",
                    (DATASET_VERSION,),
                )
            ).fetchall()
            # PostgreSQL numeric/date representations are normalized for comparison.
            encode = lambda values: json.dumps(values, default=str, ensure_ascii=False)
            actual = [list(row) for row in rows]
            wanted = [list(row) for row in expected]
            if table == "customer_activity":
                for row in actual:
                    row[3] = float(row[3])
            if encode(actual) != encode(wanted):
                raise ValueError(f"synthetic dataset mismatch: {table}")
    return {
        "dataset_version": DATASET_VERSION,
        "customers": len(customers),
        "activity": len(activity),
        "synthetic": True,
    }


async def load_training_data(
    database_url: str,
) -> tuple[list[list[float]], list[int], str]:
    # Deliberate allowlist: no identifier, contact, birth, income or credit-score features.
    async with connect(database_url) as connection:
        rows = await (
            await connection.execute(
                """SELECT tenure_months, monthly_spend,
            login_days_30d, support_tickets_30d, churned
            FROM mlops_demo.customer_activity WHERE dataset_version=%s AND is_synthetic
            ORDER BY customer_id""",
                (DATASET_VERSION,),
            )
        ).fetchall()
    if len(rows) != 600:
        raise ValueError("expected exactly 600 rows of the frozen demo dataset")
    values = [[float(value) for value in row[:4]] for row in rows]
    labels = [int(row[4]) for row in rows]
    checksum = hashlib.sha256(
        json.dumps([values, labels], separators=(",", ":")).encode()
    ).hexdigest()
    return values, labels, checksum
