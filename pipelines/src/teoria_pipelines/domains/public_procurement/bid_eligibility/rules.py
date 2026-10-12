from __future__ import annotations

import re


def _bind_standard_rules(result: dict) -> None:
    """Compile normalized extraction facts to versioned standard eligibility rules."""
    standard_rules = {
        "industry_license": "has_registered_industry",
        "participation_region": "satisfies_participation_region",
        "product_registration": "has_registered_supply_product",
    }
    for requirement in result["requirements"]:
        value = requirement.get("value") or {}
        proposition = str(
            requirement.get("proposition_text") or requirement.get("original_text") or ""
        )
        attributes = {
            str(item.get("name") or "").casefold(): item.get("value")
            for item in value.get("attributes", [])
        }
        arguments: dict[str, object] = {}
        standard_rule_id = standard_rules.get(requirement["type"])
        if requirement["type"] == "business_status":
            if attributes.get("business_status_type") == "active_business_registration":
                standard_rule_id = "is_active_business"
        elif requirement["type"] == "procurement_registration":
            if attributes.get("procurement_registration_type") == "supplier_registration":
                standard_rule_id = "is_registered_procurement_supplier"
        elif requirement["type"] == "industry_license":
            arguments["expected_value"] = (
                attributes.get("industry_code") or value.get("items") or value.get("text")
            )
        elif requirement["type"] == "participation_region":
            arguments["expected_value"] = (
                attributes.get("region_code") or value.get("items") or value.get("text")
            )
        elif requirement["type"] == "product_registration":
            arguments["product_code"] = (
                attributes.get("product_code")
                or attributes.get("detailed_product_code")
                or value.get("items")
                or value.get("text")
            )
        elif requirement["type"] == "certificate":
            certificate_type = attributes.get("certificate_type")
            qualification_type = attributes.get("qualification_type")
            if certificate_type == "direct_production_confirmation":
                product_codes = set(re.findall(r"(?<!\d)\d{10}(?!\d)", proposition))
                if len(product_codes) <= 1:
                    standard_rule_id = "holds_valid_direct_production_confirmation"
                    arguments = {}
                    product_code = attributes.get("product_code") or attributes.get("detailed_product_code")
                    if product_code:
                        arguments["product_code"] = product_code
            elif qualification_type in {
                "women_owned_business", "disabled_owned_business",
                "venture_business", "innobiz", "mainbiz",
            }:
                standard_rule_id = "holds_valid_company_qualification"
                arguments["qualification_type"] = qualification_type
        elif requirement["type"] == "company_scale":
            company_scale = attributes.get("company_scale") or value.get("text") or value.get("items")
            if company_scale:
                standard_rule_id = "has_company_scale_qualification"
                arguments["company_scale"] = company_scale
        elif requirement["type"] == "consortium":
            participation_mode = str(attributes.get("participation_mode") or "")
            if (
                participation_mode in {"consortium", "single_only"}
                and isinstance(value.get("boolean"), bool)
            ):
                standard_rule_id = "is_consortium_allowed"
                arguments["consortium_allowed"] = value["boolean"]
        elif requirement["type"] == "sanction":
            has_post_sanction_period = bool(re.search(
                r"(?:종료일|제재[\s·]*종료).{0,30}\d+\s*(?:개월|년)", proposition
            ))
            if (
                attributes.get("sanction_type") == "procurement_participation_restriction"
                and not has_post_sanction_period
            ):
                standard_rule_id = "has_no_active_procurement_sanction"
        requirement["standard_rule_id"] = standard_rule_id
        requirement["standard_rule_version"] = (
            "1.1.0" if standard_rule_id == "holds_valid_company_qualification"
            else "1.1.0" if standard_rule_id == "has_registered_industry"
            else "1.0.0" if standard_rule_id else None
        )
        requirement["rule_arguments"] = arguments
