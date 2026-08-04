from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from teoria_pipelines.models import ExtractedBatch, NormalizedBatch, RawProviderRecord

CONTRACT_TYPES = {
    "list_goods_contracts": "goods",
    "list_construction_contracts": "construction",
    "list_service_contracts": "service",
    "list_foreign_procurement_contracts": "foreign_procurement",
}


class ContractNormalizationError(ValueError):
    pass


def normalize_contract_batch(batch: ExtractedBatch) -> NormalizedBatch:
    normalized = NormalizedBatch()
    organizations: dict[str, dict[str, Any]] = {}
    for record in batch.records:
        contract, suppliers, demands, record_organizations = normalize_contract_record(record)
        normalized.contracts.append(contract)
        normalized.suppliers.extend(suppliers)
        normalized.demand_organizations.extend(demands)
        for organization in record_organizations:
            organizations[organization["organization_code"]] = organization
    normalized.organizations = list(organizations.values())
    return normalized


def normalize_contract_record(record: RawProviderRecord):
    value = record.payload
    unified_number = _text(value.get("untyCntrctNo"))
    if not unified_number:
        raise ContractNormalizationError(
            f"{record.operation_id} record is missing untyCntrctNo"
        )
    contract_type = CONTRACT_TYPES.get(record.operation_id)
    if contract_type is None:
        raise ContractNormalizationError(f"unsupported operation '{record.operation_id}'")
    currency_default = None if contract_type == "foreign_procurement" else "KRW"
    contract = {
        "unified_contract_number": unified_number,
        "contract_type": contract_type,
        "confirmed_contract_number": _text(value.get("dcsnCntrctNo")),
        "contract_reference_number": _text(value.get("cntrctRefNo")),
        "contract_name": _text(value.get("cntrctNm") or value.get("cnstwkNm")),
        "is_joint_contract": _boolean(value.get("cmmnCntrctYn")),
        "long_term_continuation_type": _text(value.get("lngtrmCtnuDivNm")),
        "concluded_date": _date(value.get("cntrctCnclsDate")),
        "contract_date": _date(value.get("cntrctDate")),
        "contract_period_text": _text(value.get("cntrctPrd")),
        "basis_law_name": _text(value.get("baseLawNm")),
        "total_amount": _decimal(value.get("totCntrctAmt")),
        "total_amount_currency": _text(value.get("totCntrctAmtCrncy")) or currency_default,
        "current_contract_amount": _decimal(value.get("thtmCntrctAmt")),
        "current_contract_amount_currency": _text(value.get("thtmCntrctAmtCrncy")) or currency_default,
        "guarantee_deposit_rate": _decimal(value.get("grntymnyRate")),
        "payment_method_name": _text(value.get("payDivNm")),
        "request_number": _text(value.get("reqNo")),
        "notice_number": _text(value.get("ntceNo")),
        "contract_method_name": _text(value.get("cntrctCnclsMthdNm")),
        "contracting_organization_code": _text(value.get("cntrctInsttCd")),
        "contracting_department_name": _text(value.get("cntrctInsttChrgDeptNm")),
        "procurement_classification_number": _text(value.get("pubPrcrmntClsfcNo")),
        "procurement_classification_name": _text(value.get("pubPrcrmntClsfcNm")),
        "contract_information_url": _text(value.get("cntrctInfoUrl")),
        "contract_detail_url": _text(value.get("cntrctDtlInfoUrl")),
        "source_registered_at": _datetime(value.get("rgstDt")),
        "source_changed_at": _datetime(value.get("chgDt")),
        "source_record_hash": record.source_record_hash,
    }

    suppliers = []
    for fields in _parse_bracket_list(value.get("corpList"), expected_fields=10):
        business_number = re.sub(r"\D", "", fields[9]) or None
        suppliers.append({
            "unified_contract_number": unified_number,
            "supplier_sequence": _integer(fields[0]),
            "supplier_role_name": _text(fields[1]),
            "joint_contract_method_name": _text(fields[2]),
            "business_registration_number": business_number,
            "supplier_name": _text(fields[3]),
            "representative_name": _text(fields[4]),
            "nationality_name": _text(fields[5]),
            "participation_share_rate": _decimal(fields[6]),
            "creditor_name": _text(fields[7]),
            "supplier_manager_name": _text(fields[8]),
        })

    demands = []
    organizations = []
    contracting_code = contract["contracting_organization_code"]
    if contracting_code:
        organizations.append({
            "organization_code": contracting_code,
            "organization_name": _text(value.get("cntrctInsttNm")),
            "jurisdiction_type": _text(value.get("cntrctInsttJrsdctnDivNm")),
        })
    for fields in _parse_bracket_list(value.get("dminsttList"), expected_fields=7):
        organization_code = _text(fields[1])
        demands.append({
            "unified_contract_number": unified_number,
            "demand_organization_sequence": _integer(fields[0]),
            "organization_code": organization_code,
            "department_name": _text(fields[4]),
            "manager_name": _text(fields[5]),
            "telephone_number": _text(fields[6]),
        })
        if organization_code:
            organizations.append({
                "organization_code": organization_code,
                "organization_name": _text(fields[2]),
                "jurisdiction_type": _text(fields[3]),
            })
    return contract, suppliers, demands, organizations


def _parse_bracket_list(value: Any, *, expected_fields: int) -> list[list[str]]:
    text = _text(value)
    if not text:
        return []
    if not (text.startswith("[") and text.endswith("]")):
        raise ContractNormalizationError("list value does not use documented bracket format")
    # Provider values may contain literal brackets inside a field (for example a
    # supplier's English name). Only `],[` separates records in this wire format.
    records = re.split(r"\]\s*,\s*\[", text[1:-1])
    parsed: list[list[str]] = []
    for index, record in enumerate(records):
        fields = [field.strip() for field in record.split("^")]
        if len(fields) != expected_fields:
            raise ContractNormalizationError(
                f"list entry {index} has {len(fields)} fields; expected {expected_fields}"
            )
        parsed.append(fields)
    return parsed


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _integer(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ContractNormalizationError(f"invalid integer value {value!r}") from exc


def _decimal(value: Any) -> Decimal | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation as exc:
        raise ContractNormalizationError(f"invalid decimal value {value!r}") from exc


def _boolean(value: Any) -> bool | None:
    text = (_text(value) or "").upper()
    if not text:
        return None
    if text in {"Y", "YES", "TRUE", "1"}:
        return True
    if text in {"N", "NO", "FALSE", "0"}:
        return False
    raise ContractNormalizationError(f"invalid boolean value {value!r}")


def _date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ContractNormalizationError(f"invalid date value {value!r}")


def _datetime(value: Any) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    raise ContractNormalizationError(f"invalid datetime value {value!r}")
