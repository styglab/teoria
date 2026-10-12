from __future__ import annotations


PROCESSOR_ID = "assessment.evaluate_bid_eligibility"


BATCH_PROCESSOR_ID = "assessment.evaluate_bid_eligibilities"


RULESET_VERSION = "1.0.0"


CACHE_TTL_SECONDS = 300.0


CACHE_MAX_ENTRIES = 2048


KEY_OUTCOME_CATEGORIES = (
    "participation_region",
    "industry_license",
    "business_status",
    "procurement_registration",
    "company_qualification",
    "company_scale",
    "direct_production",
    "supply_product",
    "sanction",
    "consortium",
    "past_performance",
    "custom",
)


RULE_OUTCOME_CATEGORIES = {
    "satisfies_participation_region": "participation_region",
    "has_registered_industry": "industry_license",
    "is_active_business": "business_status",
    "is_registered_procurement_supplier": "procurement_registration",
    "is_valid_women_owned_business": "company_qualification",
    "is_valid_disabled_owned_business": "company_qualification",
    "holds_valid_company_qualification": "company_qualification",
    "has_company_scale_qualification": "company_scale",
    "holds_valid_direct_production_confirmation": "direct_production",
    "has_registered_supply_product": "supply_product",
    "has_no_active_procurement_sanction": "sanction",
    "is_consortium_allowed": "consortium",
}


TYPE_OUTCOME_CATEGORIES = {
    "participation_region": "participation_region",
    "industry_license": "industry_license",
    "business_status": "business_status",
    "procurement_registration": "procurement_registration",
    "company_scale": "company_scale",
    "product_registration": "supply_product",
    "sanction": "sanction",
    "consortium": "consortium",
    "past_performance": "past_performance",
}
