from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.assessment.models import CompanyEvidenceSnapshot, EvaluationDecision, requirement_value
from teoria.runtime.mapping.materializer import MaterializedObject


def evaluate_requirement(
    requirement: MaterializedObject,
    snapshot: CompanyEvidenceSnapshot,
    reference_date: date,
    catalog: RegistryCatalog,
) -> EvaluationDecision:
    properties = requirement.properties
    standard_rule_id = str(properties.get("standard_rule_id") or "")
    standard_rule = catalog.eligibility_rules.get(standard_rule_id)
    if standard_rule is None:
        return EvaluationDecision("needs_review", "unsupported_standard_rule", "")
    handlers = {
        "business_status_active": _business_status,
        "procurement_supplier_registered": _procurement_registration,
        "industry_registration_matches": _industry_license,
        "participation_region_matches": _participation_region,
        "qualification_valid": _qualification,
        "company_scale_qualification_valid": _company_scale,
        "product_certificate_valid": _product_certificate,
        "product_registration_matches": _product_registration,
        "no_active_sanction": _sanction,
        "consortium_participation_allowed": _consortium_allowed,
    }
    handler = handlers.get(standard_rule.evaluator)
    if handler is None:
        return EvaluationDecision("needs_review", "unsupported_rule_evaluator", "")
    bound_properties = {**properties, "_standard_rule_id": standard_rule_id}
    return handler(bound_properties, snapshot, reference_date)


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


def _industry_license(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, reference_date: date) -> EvaluationDecision:
    if "get_procurement_supplier_industries" in snapshot.unavailable_capabilities:
        return _unavailable()
    expected = _expected_values(properties, "expected_value")
    industries = snapshot.by_type("registered_industry")
    matched = [
        item for item in industries
        if _matches(expected, item.properties.get("industry_code"), item.properties.get("industry_name"))
    ]
    if not expected:
        return EvaluationDecision("needs_review", "ambiguous_requirement", "")
    active = [item for item in matched if _registered_industry_active_on(item, reference_date)]
    if active:
        return EvaluationDecision("satisfied", "industry_code_matched", _display(active), active)
    if matched:
        return EvaluationDecision("unsatisfied", "industry_registration_inactive", _display(matched), matched)
    return EvaluationDecision("unsatisfied", "industry_code_mismatched", _display(industries), industries)


def _registered_industry_active_on(item: MaterializedObject, reference_date: date) -> bool:
    registered_at = _date(item.properties.get("registered_at"))
    valid_until = _date(item.properties.get("valid_until"))
    status = _normalize(str(item.properties.get("status_name") or ""))
    inactive_status = any(token in status for token in ("말소", "폐업", "취소", "정지", "만료", "유효기간경과"))
    return (
        not inactive_status
        and (registered_at is None or registered_at <= reference_date)
        and (valid_until is None or reference_date <= valid_until)
    )


def _participation_region(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, _: date) -> EvaluationDecision:
    if "get_procurement_supplier" in snapshot.unavailable_capabilities:
        return _unavailable()
    expected = _expected_values(properties, "expected_value")
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


def _qualification(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, reference_date: date) -> EvaluationDecision:
    qualification_type = str(_rule_arguments(properties).get("qualification_type") or "") or {
        "is_valid_women_owned_business": "women_owned_business",
        "is_valid_disabled_owned_business": "disabled_owned_business",
    }.get(str(properties.get("_standard_rule_id") or ""), "")
    if qualification_type in {"venture_business", "innobiz", "mainbiz"}:
        return _innovation_qualification(qualification_type, snapshot, reference_date)
    if qualification_type not in {"women_owned_business", "disabled_owned_business"}:
        return EvaluationDecision("needs_review", "unsupported_qualification_type", "")
    capability = "get_company_qualifications"
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


def _innovation_qualification(
    qualification_type: str,
    snapshot: CompanyEvidenceSnapshot,
    reference_date: date,
) -> EvaluationDecision:
    capability = {
        "venture_business": "verify_venture_company",
        "innobiz": "verify_innobiz_company",
        "mainbiz": "verify_mainbiz_company",
    }[qualification_type]
    if capability in snapshot.unavailable_capabilities:
        return _unavailable()
    if qualification_type == "venture_business":
        disclosures = snapshot.by_type("venture_company_disclosure")
        if disclosures:
            return EvaluationDecision("satisfied", "qualification_valid", _display(disclosures), disclosures)
        return EvaluationDecision("unsatisfied", "qualification_missing", "")
    observations = [
        item for item in snapshot.by_type("innovation_certification_observation")
        if item.properties.get("certification_kind") == qualification_type
    ]
    valid = _valid_on(observations, reference_date)
    if valid:
        return EvaluationDecision("satisfied", "qualification_valid", _display(valid), valid)
    if observations:
        return EvaluationDecision("unsatisfied", "qualification_expired", _display(observations), observations)
    return EvaluationDecision("unsatisfied", "qualification_missing", "")


def _company_scale(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, reference_date: date) -> EvaluationDecision:
    expected = _expected_values(properties, "company_scale")
    if not expected:
        return EvaluationDecision("needs_review", "ambiguous_requirement", "")
    # No registered Source currently proves the bid-date validity and detailed scale
    # represented by an official SME/small-business/micro-enterprise confirmation.
    # Generic company facts and unrelated qualifications are never sufficient.
    return EvaluationDecision("needs_review", "company_scale_document_required", ", ".join(expected))


def _consortium_allowed(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, _: date) -> EvaluationDecision:
    mode = str(snapshot.assessment_context.get("participation_mode") or "single")
    required = requirement_value(properties)
    allowed = required.get("boolean")
    if allowed is None:
        allowed = _rule_arguments(properties).get("consortium_allowed")
    if isinstance(allowed, str):
        allowed = allowed.casefold() in {"true", "1", "yes", "allowed"}
    if mode == "single":
        return EvaluationDecision("satisfied", "single_participation_selected", mode)
    if mode != "consortium":
        return EvaluationDecision("needs_review", "ambiguous_participation_mode", mode)
    if allowed is True:
        return EvaluationDecision("satisfied", "consortium_participation_allowed", mode)
    if allowed is False:
        return EvaluationDecision("unsatisfied", "consortium_participation_prohibited", mode)
    return EvaluationDecision("needs_review", "ambiguous_requirement", mode)


def _product_certificate(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, reference_date: date) -> EvaluationDecision:
    arguments = _rule_arguments(properties)
    if "get_direct_production_confirmations" in snapshot.unavailable_capabilities:
        return _unavailable()
    expected_code = str(arguments.get("product_code") or "")
    confirmations = _valid_on(snapshot.by_type("direct_production_confirmation"), reference_date)
    matched = [
        item for item in confirmations
        if not expected_code or str(item.properties.get("detailed_product_code") or "") == expected_code
    ]
    if matched:
        return EvaluationDecision("satisfied", "direct_production_matched", _display(matched), matched)
    return EvaluationDecision("unsatisfied", "direct_production_mismatched", _display(confirmations), confirmations)


def _rule_arguments(properties: dict[str, Any]) -> dict[str, Any]:
    raw = properties.get("rule_arguments_text")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        import json
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError):
            pass
    return requirement_value(properties)


def _product_registration(properties: dict[str, Any], snapshot: CompanyEvidenceSnapshot, _: date) -> EvaluationDecision:
    if "get_procurement_supplier_products" in snapshot.unavailable_capabilities:
        return _unavailable()
    expected = _expected_values(properties, "product_code")
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
    expects_absence = operator in {"not_exists", "not_equals", "not_in"} or "없" in str(properties.get("original_text") or "")
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


def _expected_values(properties: dict[str, Any], argument_name: str) -> list[str]:
    arguments = _rule_arguments(properties)
    value = arguments.get(argument_name)
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and item != ""]
    if value not in {None, ""}:
        return [str(value)]
    return _candidate_values(requirement_value(properties))


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
    preferred = ("operating_status", "industry_code", "region_code", "qualification_type", "certification_kind", "status", "detailed_product_code", "status_name")
    for item in objects[:10]:
        value = next((item.properties.get(key) for key in preferred if item.properties.get(key) not in {None, ""}), item.object_id)
        values.append(str(value))
    return ", ".join(values)


def _unavailable() -> EvaluationDecision:
    return EvaluationDecision("needs_review", "source_unavailable", "")
