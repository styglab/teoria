"""Compatibility exports for the decomposed eligibility assessment."""

from .assessment import (
    execute_bid_eligibility_assessment,
    _execute_bid_eligibility_assessment_uncached,
    execute_bid_eligibility_assessments,
    _notice_reference_date,
    _split_bid_notice_id,
)
from .assessment_cache import (
    _runtime_cache,
    clear_assessment_cache,
    _get_company_evidence_cache,
    _put_company_evidence_cache,
    _assessment_fingerprint,
    _get_batch_summary_cache,
    _put_batch_summary_cache,
    _hash,
    _assessment_cache,
    _batch_summary_cache,
    _company_evidence_cache,
)
from .assessment_policy import (
    PROCESSOR_ID,
    BATCH_PROCESSOR_ID,
    RULESET_VERSION,
    CACHE_TTL_SECONDS,
    CACHE_MAX_ENTRIES,
    KEY_OUTCOME_CATEGORIES,
    RULE_OUTCOME_CATEGORIES,
    TYPE_OUTCOME_CATEGORIES,
)
from .evidence_loader import _load_company_evidence_for_dates, _load_company_evidence, logger
from .evidence_snapshot import _snapshot_from_results, _merge_snapshots, _objects, _company_id
from .expression_projection import _project_expression, _parse_expression
from .outcomes import (
    _key_outcomes,
    evaluate_requirement_category,
    _requirement_outcome_category,
    _aggregate_assessment,
    _participation_evaluations,
)
from .result_builder import (
    _materialize_batch_summary,
    _materialize_result,
    _notice_evidence,
    _source_evidence,
    _object,
    _link,
    _reasoning,
)
