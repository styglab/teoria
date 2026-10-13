from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

import psycopg

from teoria.domains.public_procurement.bid_eligibility.assessment import (
    execute_bid_eligibility_assessment,
    execute_bid_eligibility_assessments,
)
from teoria.domains.public_procurement.market_analysis.activity import (
    execute_procurement_activity_search,
)
from teoria.domains.public_procurement.market_analysis.bid_context.bid_participation import (
    execute_bid_participation_context,
)
from teoria.domains.public_procurement.market_analysis.bid_context.notice_relationship import (
    execute_bid_notice_relationship_context,
)
from teoria.domains.public_procurement.market_analysis.contracts.contract_search import (
    enrich_contract_search_objects,
)
from teoria.domains.public_procurement.market_analysis.contracts.project_lineage import (
    execute_bid_project_lineage,
)
from teoria.domains.public_procurement.market_analysis.outcomes import (
    execute_procurement_outcome_search,
)
from teoria.domains.public_procurement.market_analysis.participation import (
    execute_company_participation_search,
    execute_bid_notice_participations,
    execute_company_competitor_analysis,
)
from teoria.domains.public_procurement.market_analysis.profiles.profiles import (
    execute_organization_procurement_profile,
    execute_company_procurement_profile,
    execute_organization_supplier_entry_search,
)
from teoria.domains.public_procurement.market_analysis.related_projects.search import (
    execute_bid_related_projects_search,
)
from teoria.domains.public_procurement.market_analysis.related_projects.similar_experience import (
    execute_company_similar_project_experience,
)
from teoria.domains.public_procurement.market_analysis.relationships.organization_relationship import (
    execute_organization_company_relationship,
)
from teoria.domains.public_procurement.exploration import (
    execute_autocomplete_procurement_entities,
    execute_procurement_classification_catalog,
    execute_procurement_field_market,
    execute_procurement_network,
    execute_procurement_region_filter_options,
)
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityExecutionError, CapabilityResult
from teoria.runtime.capability.handlers import CapabilityHandlers

if TYPE_CHECKING:
    from teoria.runtime.capability.runner import CapabilityRunner


def _query(
    handler: Callable[..., Awaitable[CapabilityResult]], *, cache: bool = False,
):
    async def execute(
        runner: CapabilityRunner, catalog: RegistryCatalog,
        capability_id: str, inputs: dict[str, Any],
    ) -> CapabilityResult:
        options = {"cache": runner.cache} if cache else {}
        return await handler(catalog, capability_id, inputs, **options)

    return execute


async def _enrich_contract_search(
    runner: CapabilityRunner, catalog: RegistryCatalog,
    result: CapabilityResult, observed_at: datetime,
) -> CapabilityResult:
    try:
        await enrich_contract_search_objects(catalog, result.objects, observed_at=observed_at)
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=result.capability_id,
            source_id="teoria_public_procurement", operation_id="contract_suppliers",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc
    return result


def register_processors(handlers: CapabilityHandlers) -> None:
    handlers.register_processor(
        "procurement_exploration.autocomplete_procurement_entities",
        _query(execute_autocomplete_procurement_entities, cache=True),
    )
    handlers.register_processor(
        "procurement_exploration.get_procurement_network",
        _query(execute_procurement_network, cache=True),
    )
    handlers.register_processor(
        "procurement_exploration.analyze_procurement_field_market",
        _query(execute_procurement_field_market, cache=True),
    )
    handlers.register_processor(
        "procurement_exploration.get_procurement_classification_catalog",
        _query(execute_procurement_classification_catalog, cache=True),
    )
    handlers.register_processor(
        "procurement_exploration.get_procurement_region_filter_options",
        _query(execute_procurement_region_filter_options, cache=True),
    )
    handlers.register_processor(
        "assessment.evaluate_bid_eligibility", execute_bid_eligibility_assessment,
    )
    handlers.register_processor(
        "assessment.evaluate_bid_eligibilities", execute_bid_eligibility_assessments,
    )
    handlers.register_processor(
        "market_context.find_bid_project_lineage", _query(execute_bid_project_lineage),
    )
    handlers.register_processor(
        "market_context.get_organization_company_relationship", _query(execute_organization_company_relationship, cache=True),
    )
    handlers.register_processor(
        "market_context.get_company_similar_project_experience", _query(execute_company_similar_project_experience),
    )
    handlers.register_processor(
        "market_context.analyze_organization_procurement_profile", _query(execute_organization_procurement_profile),
    )
    handlers.register_processor(
        "market_context.analyze_company_procurement_profile", _query(execute_company_procurement_profile),
    )
    handlers.register_processor(
        "market_context.search_organization_supplier_entries", _query(execute_organization_supplier_entry_search),
    )
    handlers.register_processor(
        "market_context.search_company_bid_participations", _query(execute_company_participation_search),
    )
    handlers.register_processor(
        "market_context.get_bid_notice_participations", _query(execute_bid_notice_participations),
    )
    handlers.register_processor(
        "market_context.analyze_company_competitors", _query(execute_company_competitor_analysis),
    )
    handlers.register_processor(
        "market_context.get_bid_notice_relationship_context", _query(execute_bid_notice_relationship_context),
    )
    handlers.register_processor(
        "market_context.analyze_bid_participation_context", _query(execute_bid_participation_context, cache=True),
    )
    handlers.register_processor(
        "market_context.search_bid_related_projects", _query(execute_bid_related_projects_search, cache=True),
    )
    handlers.register_processor(
        "market_context.search_procurement_outcomes", _query(execute_procurement_outcome_search),
    )
    handlers.register_processor(
        "market_context.search_procurement_activity", _query(execute_procurement_activity_search),
    )
    handlers.register_query_hook("search_public_procurement_contracts", _enrich_contract_search)
