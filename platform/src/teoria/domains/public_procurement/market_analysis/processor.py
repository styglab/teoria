"""Compatibility exports; use the named feature modules for new callers."""

from .activity import (
    _notice_group_id,
    _group_procurement_activity_records,
    execute_procurement_activity_search,
    _PROCUREMENT_ACTIVITY_STAGE_PRIORITY,
)
from .bid_context.bid_participation import (
    execute_bid_participation_context,
    _BID_PARTICIPATION_CONTEXT_CACHE,
)
from .bid_context.notice_relationship import execute_bid_notice_relationship_context
from .bid_context.peer_benchmark import (
    _representative_notice_amount,
    _midrank_percentile,
    _distribution,
    _build_peer_benchmark,
)
from .bid_context.supplier_selection import (
    build_attention_suppliers as _build_attention_suppliers,
    contract_time_relationship as _contract_time_relationship,
)
from .company_evidence import (
    _load_company_evidence,
    _relevant_company_item,
    _industry_license_eligibility,
    _region_eligibility,
)
from .contracts.contract_lineage import (
    _contract_structure,
    _contract_phase_number,
    _contract_family_name,
    _contract_event_identity,
    _contract_source_numbers,
    _official_contract_change_identity,
    _decorate_contract_amount,
    _decorate_contract_lineage,
    _decorate_contract_series,
    _contract_family_summary,
    _CONTRACT_PHASE_PATTERN,
    _CONTRACT_FAMILY_MARKER_PATTERN,
)
from .contracts.contract_search import enrich_contract_search_objects
from .contracts.project_lineage import execute_bid_project_lineage
from .field_identity import (
    _normalized_category,
    _effective_large_category,
    _effective_middle_category,
    _procurement_field_identity,
)
from .outcomes import _outcome_contractor, execute_procurement_outcome_search
from .participation import (
    _participation_matches_filters,
    execute_company_participation_search,
    execute_bid_notice_participations,
    execute_company_competitor_analysis,
)
from .periods import _fiscal_period_start, _shift_years, _resolve_profile_period
from .profiles.market_structure import (
    _rolling_12m_supplier_entry,
    _supplier_entry,
    _organization_entry,
    _contract_method_group,
    _organization_market_structure,
    _previous_period_comparison,
)
from .profiles.profile_aggregation import (
    _amount_completeness,
    _filter_profile_rows,
    _contract_project_key,
    _collapse_profile_contract_versions,
    _drilldown_field_distribution,
    _profile_aggregate,
)
from .profiles.profiles import (
    _execute_procurement_profile,
    execute_organization_procurement_profile,
    execute_company_procurement_profile,
    execute_organization_supplier_entry_search,
)
from .related_projects.search import execute_bid_related_projects_search, _similar_notice_item
from .related_projects.similar_experience import (
    execute_company_similar_project_experience,
    _execute_company_similar_project_experience_body,
    _title_project_comparison,
)
from .relationships.organization_metrics import (
    _organization_field_analysis_basis,
    _canonical_contract_notice_number,
    _organization_relationship_metrics,
    _organization_field_event_analysis,
)
from .relationships.organization_relationship import (
    execute_organization_company_field_relationship,
    execute_organization_company_relationship,
    _ORGANIZATION_FIELD_CACHE,
    _ORGANIZATION_COMPANY_FIELD_CACHE,
)
from .signal_policy import (
    SIGNAL_POLICY_VERSION,
    RECENT_ACTIVITY_DAYS,
    SIMILARITY_PROFILE,
    ORGANIZATION_FIELD_CACHE_TTL_SECONDS,
)


__all__ = [
    'enrich_contract_search_objects',
    'execute_bid_project_lineage',
    'execute_organization_company_field_relationship',
    'execute_organization_company_relationship',
    '_ORGANIZATION_FIELD_CACHE',
    '_ORGANIZATION_COMPANY_FIELD_CACHE',
    'execute_company_similar_project_experience',
    '_execute_company_similar_project_experience_body',
    '_title_project_comparison',
    '_normalized_category',
    '_effective_large_category',
    '_effective_middle_category',
    '_procurement_field_identity',
    '_fiscal_period_start',
    '_shift_years',
    '_resolve_profile_period',
    '_amount_completeness',
    '_filter_profile_rows',
    '_contract_project_key',
    '_collapse_profile_contract_versions',
    '_drilldown_field_distribution',
    '_profile_aggregate',
    '_rolling_12m_supplier_entry',
    '_supplier_entry',
    '_organization_entry',
    '_contract_method_group',
    '_organization_market_structure',
    '_previous_period_comparison',
    '_execute_procurement_profile',
    'execute_organization_procurement_profile',
    'execute_company_procurement_profile',
    'execute_organization_supplier_entry_search',
    '_participation_matches_filters',
    'execute_company_participation_search',
    'execute_bid_notice_participations',
    'execute_company_competitor_analysis',
    '_outcome_contractor',
    'execute_procurement_outcome_search',
    '_contract_structure',
    '_contract_phase_number',
    '_contract_family_name',
    '_contract_event_identity',
    '_contract_source_numbers',
    '_official_contract_change_identity',
    '_decorate_contract_amount',
    '_decorate_contract_lineage',
    '_decorate_contract_series',
    '_contract_family_summary',
    '_CONTRACT_PHASE_PATTERN',
    '_CONTRACT_FAMILY_MARKER_PATTERN',
    '_notice_group_id',
    '_group_procurement_activity_records',
    'execute_procurement_activity_search',
    '_PROCUREMENT_ACTIVITY_STAGE_PRIORITY',
    'execute_bid_notice_relationship_context',
    '_representative_notice_amount',
    '_midrank_percentile',
    '_distribution',
    '_build_peer_benchmark',
    'execute_bid_participation_context',
    '_BID_PARTICIPATION_CONTEXT_CACHE',
    '_load_company_evidence',
    '_relevant_company_item',
    '_industry_license_eligibility',
    '_region_eligibility',
    '_organization_field_analysis_basis',
    '_canonical_contract_notice_number',
    '_organization_relationship_metrics',
    '_organization_field_event_analysis',
    'execute_bid_related_projects_search',
    '_similar_notice_item',
    'SIGNAL_POLICY_VERSION',
    'RECENT_ACTIVITY_DAYS',
    'SIMILARITY_PROFILE',
    'ORGANIZATION_FIELD_CACHE_TTL_SECONDS',
    '_build_attention_suppliers',
    '_contract_time_relationship',
]
