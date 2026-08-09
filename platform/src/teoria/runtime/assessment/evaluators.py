from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from teoria.runtime.assessment.models import CompanyEvidenceSnapshot, EvaluationDecision, requirement_value
from teoria.runtime.mapping.materializer import MaterializedObject


def evaluate_requirement(
    requirement: MaterializedObject,
    snapshot: CompanyEvidenceSnapshot,
    reference_date: date,
) -> EvaluationDecision:
    properties = requirement.properties
    requirement_type = str(properties.get("requirement_type") or "custom")
    handlers = {
        "business_status": _business_status,
        "procurement_registration": _procurement_registration,
        "industry_license": _industry_license,
        "participation_region": _participation_region,
        "certificate": _certificate,
        "product_registration": _product_registration,
        "sanction": _sanction,
    }
    handler = handlers.get(requirement_type)
    if handler is None:
        return EvaluationDecision("needs_review", "unsupported_requirement", "")
    return handler(properties, snapshot, reference_date)


def _business_status(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, _: date) -> EvaluationDecision:
    if "get_business_registration_status" in snapshot.unavailable_capabilities:
        return _unavailable()
    objects = snapshot.by_type("taxpayer_status_observation")
    active = [item for item in objects if item.properties.get("operating_status") == "active"]
    if active:
        return EvaluationDecision("satisfied", "business_active", "active", active)
    if objects:
        value = str(objects[0].properties.get("operating_status") or "unknown")
        return EvaluationDecision("unsatisfied", "business_closed", value, objects[:1])
    return EvaluationDecision("needs_review", "evidence_missing", "")


def _procurement_registration(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, _: date) -> EvaluationDecision:
    if "get_procurement_supplier" in snapshot.unavailable_capabilities:
        return _unavailable()
    suppliers = snapshot.by_type("procurement_supplier")
    return (
        EvaluationDecision("satisfied", "procurement_supplier_registered", "registered", suppliers[:1])
        if suppliers
        else EvaluationDecision("unsatisfied", "procurement_supplier_not_registered", "not_registered")
    )


def _industry_license(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, _: date) -> EvaluationDecision:
    if "get_procurement_supplier_industries" in snapshot.unavailable_capabilities:
        return _unavailable()
    expected = _candidate_values(requirement_value(properties))
    industries = snapshot.by_type("registered_industry")
    matched = [
        item for item in industries
        if _matches(expected, item.properties.get("industry_code"), item.properties.get("industry_name"))
    ]
    if not expected:
        return EvaluationDecision("needs_review", "ambiguous_requirement", "")
    if matched:
        return EvaluationDecision("satisfied", "industry_code_matched", _display(matched), matched)
    return EvaluationDecision("unsatisfied", "industry_code_mismatched", _display(industries), industries)


def _participation_region(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, _: date) -> EvaluationDecision:
    if "get_procurement_supplier" in snapshot.unavailable_capabilities:
        return _unavailable()
    expected = _candidate_values(requirement_value(properties))
    suppliers = snapshot.by_type("procurement_supplier")
    matched = [
        item for item in suppliers
        if _matches(expected, item.properties.get("region_code"), item.properties.get("region_name"), item.properties.get("base_address"))
    ]
    if not expected:
        return EvaluationDecision("needs_review", "ambiguous_requirement", "")
    if matched:
        return EvaluationDecision("satisfied", "region_matched", _display(matched), matched)
    if suppliers:
        return EvaluationDecision("unsatisfied", "region_mismatched", _display(suppliers), suppliers)
    return EvaluationDecision("needs_review", "evidence_missing", "")


def _certificate(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, reference_date: date) -> EvaluationDecision:
    expected = _candidate_values(requirement_value(properties))
    text = " ".join(expected + [str(properties.get("original_text") or "")]).lower()
    if "직접생산" in text:
        if "get_direct_production_confirmations" in snapshot.unavailable_capabilities:
            return _unavailable()
        codes = set(re.findall(r"(?<!\d)\d{8,10}(?!\d)", text))
        confirmations = _valid_on(snapshot.by_type("direct_production_confirmation"), reference_date)
        matched = [
            item for item in confirmations
            if not codes or str(item.properties.get("detailed_product_code") or "") in codes
        ]
        if matched:
            return EvaluationDecision("satisfied", "direct_production_matched", _display(matched), matched)
        return EvaluationDecision("unsatisfied", "direct_production_mismatched", _display(confirmations), confirmations)

    qualification_type = None
    capability = None
    if "여성기업" in text:
        qualification_type, capability = "women_owned_business", "get_women_owned_business_qualification"
    elif "장애인기업" in text:
        qualification_type, capability = "disabled_owned_business", "get_disabled_owned_business_qualification"
    if qualification_type is None:
        return EvaluationDecision("needs_review", "unsupported_requirement", "")
    if capability in snapshot.unavailable_capabilities:
        return _unavailable()
    qualifications = [
        item for item in snapshot.by_type("qualification")
        if item.properties.get("qualification_type") == qualification_type
    ]
    valid = _valid_on(qualifications, reference_date)
    if valid:
        return EvaluationDecision("satisfied", "qualification_valid", _display(valid), valid)
    if qualifications:
        return EvaluationDecision("unsatisfied", "qualification_expired", _display(qualifications), qualifications)
    return EvaluationDecision("unsatisfied", "qualification_missing", "")


def _product_registration(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, _: date) -> EvaluationDecision:
    if "get_procurement_supplier_products" in snapshot.unavailable_capabilities:
        return _unavailable()
    expected = _candidate_values(requirement_value(properties))
    products = snapshot.by_type("registered_supply_product")
    matched = [
        item for item in products
        if _matches(expected, item.properties.get("detailed_product_code"), item.properties.get("detailed_product_name"))
    ]
    if not expected:
        return EvaluationDecision("needs_review", "ambiguous_requirement", "")
    if matched:
        return EvaluationDecision("satisfied", "product_registration_matched", _display(matched), matched)
    return EvaluationDecision("unsatisfied", "product_registration_mismatched", _display(products), products)


def _sanction(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, reference_date: date) -> EvaluationDecision:
    if "get_procurement_supplier_sanctions" in snapshot.unavailable_capabilities:
        return _unavailable()
    sanctions = _valid_on(snapshot.by_type("procurement_sanction"), reference_date)
    operator = str(properties.get("operator") or "")
    expects_absence = operator in {"not_exists", "not_equals"} or "없" in str(properties.get("original_text") or "")
    if not expects_absence:
        return EvaluationDecision("needs_review", "ambiguous_requirement", _display(sanctions), sanctions)
    if sanctions:
        return EvaluationDecision("unsatisfied", "active_sanction_found", _display(sanctions), sanctions)
    return EvaluationDecision("satisfied", "active_sanction_not_found", "none")


def _candidate_values(value: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("text", "number", "boolean"):
        current = value.get(key)
        if current is not None and current != "":
            values.append(str(current))
    values.extend(str(item) for item in value.get("items", []) if item is not None)
    for item in value.get("attributes", []):
        if isinstance(item, dict) and item.get("value") is not None:
            values.append(str(item["value"]))
    return values


def _matches(expected: list[str], *actual: Any) -> bool:
    normalized_expected = [_normalize(item) for item in expected if _normalize(item)]
    normalized_actual = [_normalize(str(item)) for item in actual if item is not None and _normalize(str(item))]
    return any(left == right or left in right or right in left for left in normalized_expected for right in normalized_actual)


def _normalize(value: str) -> str:
    return re.sub(r"[\s\-_,./()]+", "", value).lower()


def _valid_on(objects: list[MaterializedObject], reference_date: date) -> list[MaterializedObject]:
    valid = []
    for item in objects:
        start = _date(item.properties.get("valid_from"))
        end = _date(item.properties.get("valid_until"))
        if (start is None or start <= reference_date) and (end is None or reference_date <= end):
            valid.append(item)
    return valid


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _display(objects: list[MaterializedObject]) -> str:
    values = []
    preferred = ("operating_status", "industry_code", "region_code", "qualification_type", "detailed_product_code", "status_name")
    for item in objects[:10]:
        value = next((item.properties.get(key) for key in preferred if item.properties.get(key) not in {None, ""}), item.object_id)
        values.append(str(value))
    return ", ".join(values)


def _unavailable() -> EvaluationDecision:
    return EvaluationDecision("needs_review", "source_unavailable", "")
