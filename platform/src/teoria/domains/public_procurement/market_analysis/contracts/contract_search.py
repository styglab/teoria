from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance

from ..readers import ContractSupplierBatchReader
from ..related_projects.similarity import number as _number


async def enrich_contract_search_objects(
    catalog: RegistryCatalog, objects: list[MaterializedObject], *, observed_at: datetime,
    reader: ContractSupplierBatchReader | None = None,
) -> None:
    """Attach contractors to the already paginated contract page in one DB query."""
    contracts = [item for item in objects if item.object_type == "contract"]
    contract_numbers = [
        str(item.properties.get("unified_contract_number") or "").strip()
        for item in contracts
    ]
    contract_numbers = [value for value in contract_numbers if value]
    if not contract_numbers:
        return
    resolved_reader = reader or ContractSupplierBatchReader()
    rows = await asyncio.to_thread(
        resolved_reader.find, catalog, unified_contract_numbers=contract_numbers,
    )
    grouped: dict[str, list[dict[str, Any]]] = {value: [] for value in contract_numbers}
    record_keys: dict[str, list[str]] = {value: [] for value in contract_numbers}
    for row in rows:
        contract_number = str(row["unified_contract_number"])
        is_joint = bool(row.get("is_joint_contract"))
        source_role = str(row.get("supplier_role_name") or "").strip()
        if not is_joint:
            role, role_label = "sole", "단독"
        elif source_role == "주계약업체":
            role, role_label = "consortium_lead", "대표사"
        else:
            role, role_label = "consortium_member", "구성원"
        raw_share = row.get("participation_share_rate")
        valid_share = raw_share is not None and Decimal("0") <= Decimal(str(raw_share)) <= Decimal("100")
        grouped.setdefault(contract_number, []).append({
            "business_registration_number": row.get("business_registration_number"),
            "company_name": row.get("supplier_name"),
            "company_role": role,
            "company_role_label": role_label,
            "source_role_name": source_role or None,
            "joint_contract_method_name": row.get("joint_contract_method_name"),
            "share_percent": _number(Decimal(str(raw_share))) if valid_share else None,
            "share_completeness": (
                "complete" if valid_share else "invalid" if raw_share is not None else "unknown"
            ),
        })
        record_keys.setdefault(contract_number, []).append(
            f"teoria_public_procurement.contract_suppliers:"
            f"{contract_number}:{row.get('supplier_sequence')}"
        )
    by_number = {
        str(item.properties.get("unified_contract_number")): item for item in contracts
    }
    for contract_number in contract_numbers:
        contract = by_number[contract_number]
        contractors = grouped.get(contract_number, [])
        lead = next(
            (item for item in contractors if item["company_role"] == "consortium_lead"),
            None,
        )
        contract.properties.update({
            "contractors": contractors,
            "contractor_count": len(contractors),
            "lead_contractor": lead,
            "contractor_completeness": "complete" if contractors else "unknown",
        })
        provenance = Provenance(
            kind="source", source="teoria_public_procurement",
            operation="contract_suppliers", mapping="public_procurement",
            observed_at=observed_at, record_keys=record_keys.get(contract_number, []),
        )
        contract.provenance.append(provenance)
        for key in (
            "contractors", "contractor_count", "lead_contractor",
            "contractor_completeness",
        ):
            contract.property_provenance[key] = [provenance]
