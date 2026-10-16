from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    number = Decimal(str(value))
    return int(number) if number == number.to_integral_value() else float(number)


def _provenance(operation: str, keys: Iterable[str]) -> Provenance:
    return Provenance(
        kind="execution",
        source="teoria_runtime",
        operation=operation,
        mapping="public_procurement_exploration",
        observed_at=datetime.now(timezone.utc),
        record_keys=list(keys),
    )


def _object(
    object_type: str, object_id: str, properties: dict[str, Any], operation: str
) -> MaterializedObject:
    provenance = _provenance(operation, [object_id])
    return MaterializedObject(
        ontology="public_procurement",
        object_type=object_type,
        object_id=object_id,
        properties=properties,
        provenance=[provenance],
        property_provenance={key: [provenance] for key in properties},
    )


def _edge(row: dict[str, Any], *, hop: int) -> dict[str, Any]:
    return {
        "id": f"organization:{row['organization_code']}|company:{row['company_number']}",
        "source": {"type": "organization", "id": str(row["organization_code"])},
        "target": {"type": "company", "id": str(row["company_number"])},
        "hop": hop,
        "relationships": {
            "contract": {
                "event_count": int(row["contract_count"]),
                "attributed_amount": _number(row.get("attributed_amount")),
                "amount_completeness": row.get("amount_completeness"),
                "first_contract_date": row.get("first_contract_date"),
                "latest_contract_date": row.get("latest_contract_date"),
            },
            "award": None,
            "observed_participation": None,
            "co_participation": None,
            "joint_contract": None,
        },
    }
