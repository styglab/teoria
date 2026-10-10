from __future__ import annotations

import os
import time
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from teoria.registry.loader import RegistryCatalog

from ..queries import *  # noqa: F403

SIMILARITY_CANDIDATE_LIMIT = 300


def _enrich_procurement_classification(
    connection: Any, rows: list[dict[str, Any]],
) -> None:
    """Apply the same provider-backed hierarchy fallback to activity rows."""
    missing_codes = sorted({
        str(row["procurement_classification_number"])
        for row in rows
        if row.get("procurement_classification_number")
        and not row.get("procurement_large_classification_name")
        and not row.get("procurement_middle_classification_name")
    })
    if missing_codes:
        hierarchy = {
            str(row["procurement_classification_number"]): dict(row)
            for row in connection.execute(
                _PROCUREMENT_CLASSIFICATION_HIERARCHY_QUERY,
                {"classification_numbers": missing_codes},
            ).fetchall()
        }
        for row in rows:
            item = hierarchy.get(str(row.get("procurement_classification_number") or ""))
            if not item:
                continue
            for key in (
                "procurement_large_classification_name",
                "procurement_middle_classification_name", "purchase_items",
            ):
                if not row.get(key):
                    row[key] = item.get(key)
    notice_fields = {
        str(row["bid_notice_id"]): row for row in rows
        if row.get("procurement_classification_number")
    }
    for row in rows:
        if row.get("procurement_classification_number"):
            continue
        field = notice_fields.get(str(row.get("bid_notice_id") or ""))
        if not field:
            continue
        for key in (
            "procurement_classification_number",
            "procurement_classification_name",
            "procurement_large_classification_name",
            "procurement_middle_classification_name", "purchase_items",
        ):
            row[key] = field.get(key)


class SimilarBidNoticeReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, bid_notice_id: str, *, period_years: int,
        result_statuses: list[str], timings: dict[str, float] | None = None,
        candidate_limit: int = SIMILARITY_CANDIDATE_LIMIT,
        similarity_threshold: float = 0.15,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        notice_number, separator, notice_order = bid_notice_id.rpartition(":")
        if not separator or not notice_number or not notice_order:
            raise ValueError(f"invalid bid notice id '{bid_notice_id}'")
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT set_config('pg_trgm.similarity_threshold', %s, true)",
                (str(similarity_threshold),),
            )
            started = time.perf_counter()
            notice = connection.execute(
                """
                SELECT notice_number || ':' || notice_order AS bid_notice_id,
                       notice_name, notice_published_at::date AS notice_published_date,
                       work_type, contract_method_name,
                       estimated_price, allocated_budget, demand_organization_code,
                       demand_organization_name,
                       LEAST(now(), COALESCE(bid_deadline_at, now())) AS as_of
                FROM public_procurement.bid_notices
                WHERE notice_number=%s AND notice_order=%s
                """,
                (notice_number, notice_order),
            ).fetchone()
            if timings is not None:
                timings["current_notice_lookup_ms"] = (time.perf_counter() - started) * 1000
            if notice is None:
                raise LookupError(f"bid notice '{bid_notice_id}' was not found")
            notice["industries"] = [dict(row) for row in connection.execute(
                """
                SELECT DISTINCT substring(license_restriction_name FROM '/([0-9]{4})$')
                       AS industry_code,
                       NULLIF(regexp_replace(license_restriction_name, '/[0-9]{4}$', ''), '')
                       AS industry_name
                FROM public_procurement.bid_notice_license_restrictions
                WHERE notice_number=%s AND notice_order=%s
                  AND license_restriction_name ~ '/[0-9]{4}$'
                ORDER BY industry_code
                """,
                tuple(str(notice["bid_notice_id"]).rsplit(":", 1)),
            ).fetchall()]
            notice["industry_codes"] = [
                str(item["industry_code"]) for item in notice["industries"]
            ]
            started = time.perf_counter()
            rows = list(connection.execute(
                _SIMILAR_NOTICE_CANDIDATES_QUERY,
                {
                    "bid_notice_id": bid_notice_id,
                    "notice_number": notice_number,
                    "notice_order": notice_order,
                    "work_type": notice["work_type"],
                    "organization_code": notice["demand_organization_code"],
                    "as_of": notice["as_of"],
                    "period_years": period_years,
                    "include_awarded": "awarded" in result_statuses,
                    "include_contracted": "contracted" in result_statuses,
                    "candidate_limit": candidate_limit,
                },
            ).fetchall())
            if timings is not None:
                timings["market_similar_query_ms"] = (time.perf_counter() - started) * 1000
        return dict(notice), [dict(row) for row in rows]


class OrganizationFieldEventReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, *, organization_code: str,
        work_type: str | None, as_of: datetime,
        large_category: str | None = None, middle_category: str | None = None,
        procurement_field_code: str | None = None,
    ) -> list[dict[str, Any]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            return [dict(row) for row in connection.execute(
                _ORGANIZATION_FIELD_EVENT_ROWS_QUERY,
                {
                    "organization_code": organization_code,
                    "work_type": work_type,
                    "large_category": large_category,
                    "middle_category": middle_category,
                    "procurement_field_code": procurement_field_code,
                    "as_of": as_of,
                },
            ).fetchall()]

    def context(
        self, catalog: RegistryCatalog, *, organization_code: str,
        business_registration_number: str, reference_bid_notice_id: str | None,
    ) -> dict[str, Any]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        reference_number = reference_order = None
        if reference_bid_notice_id:
            reference_number, separator, reference_order = reference_bid_notice_id.rpartition(":")
            if not separator:
                raise ValueError(f"invalid bid notice id '{reference_bid_notice_id}'")
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            organization = connection.execute(
                "SELECT organization_code,organization_name FROM "
                "public_procurement.public_organizations WHERE organization_code=%s",
                (organization_code,),
            ).fetchone()
            company = connection.execute(
                "SELECT %s::text AS business_registration_number,company_name FROM ("
                "SELECT winner_name AS company_name,updated_at FROM public_procurement.bid_awards "
                "WHERE winner_business_registration_number=%s UNION ALL "
                "SELECT supplier_name,updated_at FROM public_procurement.contract_suppliers "
                "WHERE business_registration_number=%s) names "
                "WHERE company_name IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
                (business_registration_number, business_registration_number,
                 business_registration_number),
            ).fetchone()
            reference = None
            if reference_number and reference_order:
                reference = connection.execute(
                    "SELECT notice_number||':'||notice_order AS bid_notice_id,notice_name,work_type,"
                    "estimated_price,allocated_budget,demand_organization_code,"
                    "demand_organization_name,LEAST(now(),COALESCE(bid_deadline_at,now())) AS as_of "
                    "FROM public_procurement.bid_notices WHERE notice_number=%s AND notice_order=%s",
                    (reference_number, reference_order),
                ).fetchone()
                if reference is None:
                    raise LookupError(f"bid notice '{reference_bid_notice_id}' was not found")
                reference = dict(reference)
                reference["industry_codes"] = [str(row["industry_code"]) for row in connection.execute(
                    "SELECT DISTINCT substring(license_restriction_name FROM '/([0-9]{4})$') "
                    "AS industry_code "
                    "FROM public_procurement.bid_notice_license_restrictions "
                    "WHERE notice_number=%s AND notice_order=%s "
                    "AND license_restriction_name~'/[0-9]{4}$'",
                    (reference_number, reference_order),
                ).fetchall()]
        return {
            "organization": dict(organization) if organization else {
                "organization_code": organization_code, "organization_name": None,
            },
            "company": dict(company) if company else {
                "business_registration_number": business_registration_number,
                "company_name": None,
            },
            "reference_notice": reference,
        }


class CompanySimilarProjectExperienceReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, *, reference_bid_notice_id: str,
        business_registration_number: str, period_years: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        notice_number, separator, notice_order = reference_bid_notice_id.rpartition(":")
        if not separator:
            raise ValueError(f"invalid bid notice id '{reference_bid_notice_id}'")
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            reference = connection.execute(
                _COMPANY_SIMILAR_PROJECT_REFERENCE_QUERY,
                {"notice_number": notice_number, "notice_order": notice_order},
            ).fetchone()
            if reference is None:
                raise LookupError(f"bid notice '{reference_bid_notice_id}' was not found")
            reference = dict(reference)
            rows = connection.execute(
                _COMPANY_SIMILAR_PROJECT_EXPERIENCE_QUERY,
                {
                    "notice_number": notice_number,
                    "notice_order": notice_order,
                    "company_number": business_registration_number,
                    "period_years": period_years,
                },
            ).fetchall()
        return reference, [dict(row) for row in rows]

    def count_many(
        self, catalog: RegistryCatalog, *, reference_bid_notice_id: str,
        business_registration_numbers: list[str], period_years: int,
    ) -> dict[str, dict[str, int]]:
        if not business_registration_numbers:
            return {}
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        notice_number, separator, notice_order = reference_bid_notice_id.rpartition(":")
        if not separator:
            raise ValueError(f"invalid bid notice id '{reference_bid_notice_id}'")
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                _COMPANY_SIMILAR_PROJECT_METRICS_QUERY,
                {
                    "notice_number": notice_number,
                    "notice_order": notice_order,
                    "company_numbers": business_registration_numbers,
                    "period_years": period_years,
                },
            ).fetchall()
        return {
            str(row["company_number"]): {
                key: int(row[key]) for key in (
                    "candidate_count", "event_count", "strong_event_count",
                    "limited_event_count", "reference_only_event_count",
                    "similar_amount_event_count",
                )
            }
            for row in rows
        }


class ProcurementProfileReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def activities(
        self, catalog: RegistryCatalog, *, organization_code: str | None,
        company_numbers: list[str], period_from: date, period_to: date,
    ) -> list[dict[str, Any]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            rows = [dict(row) for row in connection.execute(
                _PROCUREMENT_PROFILE_ACTIVITIES_QUERY,
                {
                    "organization_code": organization_code,
                    "company_numbers": company_numbers,
                    "period_from": period_from,
                    "period_to": period_to,
                },
            ).fetchall()]
            _enrich_procurement_classification(connection, rows)
            return rows

    def notice_publications(
        self, catalog: RegistryCatalog, *, organization_code: str,
        period_from: date, period_to: date,
    ) -> list[dict[str, Any]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            return [dict(row) for row in connection.execute(
                _PROCUREMENT_PROFILE_NOTICES_QUERY,
                {
                    "organization_code": organization_code,
                    "period_from": period_from, "period_to": period_to,
                },
            ).fetchall()]

    def organization_award_history(
        self, catalog: RegistryCatalog, *, organization_code: str, history_from: date,
        history_to: date, work_type: str | None = None,
        large_category: str | None = None, middle_category: str | None = None,
        field_code: str | None = None,
    ) -> tuple[dict[str, date], date | None]:
        """Return first filtered contract dates in the history and target windows."""
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                _ORGANIZATION_COMPANY_FIRST_AWARD_OR_CONTRACT_QUERY,
                {
                    "organization_code": organization_code,
                    "history_from": history_from, "history_to": history_to,
                    "work_type": work_type, "large_category": large_category,
                    "middle_category": middle_category, "field_code": field_code,
                },
            ).fetchall()
        first_dates = {
            str(row["company_number"]): row["first_activity_date"]
            for row in rows if row.get("company_number") and row.get("first_activity_date")
        }
        return first_dates, history_from

    def bid_context(
        self, catalog: RegistryCatalog, *, bid_notice_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        notice_number, separator, notice_order = bid_notice_id.rpartition(":")
        if not separator:
            raise ValueError(f"invalid bid notice id '{bid_notice_id}'")
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            notice = connection.execute(
                _BID_RELATIONSHIP_NOTICE_QUERY,
                {"notice_number": notice_number, "notice_order": notice_order},
            ).fetchone()
            if notice is None:
                raise LookupError(f"bid notice '{bid_notice_id}' was not found")
            participants = connection.execute(
                _BID_RELATIONSHIP_PARTICIPANTS_QUERY,
                {"notice_number": notice_number, "notice_order": notice_order},
            ).fetchall()
        return dict(notice), [dict(row) for row in participants]

    def bid_competition(
        self, catalog: RegistryCatalog, *, organization_code: str,
        period_from: date, period_to: date,
    ) -> list[dict[str, Any]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            return [dict(row) for row in connection.execute(
                _BID_CONTEXT_COMPETITION_QUERY, {
                    "organization_code": organization_code,
                    "period_from": period_from, "period_to": period_to,
                },
            ).fetchall()]

    def peer_field_market(
        self, catalog: RegistryCatalog, *, period_from: date, period_to: date,
        history_from: date, work_type: str, large_category: str | None,
        middle_category: str | None, field_code: str | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Load official-field contract/company events and competition in two set queries."""
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        parameters = {
            "period_from": period_from, "period_to": period_to,
            "history_from": history_from, "work_type": work_type,
            "large_category": large_category, "middle_category": middle_category,
            "field_code": field_code,
        }
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            contracts = [dict(row) for row in connection.execute(
                _BID_CONTEXT_PEER_CONTRACTS_QUERY, parameters,
            ).fetchall()]
            competition = [dict(row) for row in connection.execute(
                _BID_CONTEXT_PEER_COMPETITION_QUERY, parameters,
            ).fetchall()]
        return contracts, competition

    def peer_field_contracts(self, catalog: RegistryCatalog, **parameters: Any) -> list[dict[str, Any]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            return [dict(row) for row in connection.execute(
                _BID_CONTEXT_PEER_CONTRACTS_QUERY, parameters,
            ).fetchall()]


class ProcurementOutcomeReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, *, organization_code: str,
        period_from: date, period_to: date,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            awards = [dict(row) for row in connection.execute(
                _PROCUREMENT_OUTCOME_AWARDS_QUERY,
                {
                    "organization_code": organization_code,
                    "period_from": period_from, "period_to": period_to,
                },
            ).fetchall()]
            contracts = [dict(row) for row in connection.execute(
                _PROCUREMENT_OUTCOME_CONTRACTS_QUERY,
                {
                    "organization_code": organization_code,
                    "period_from": period_from, "period_to": period_to,
                },
            ).fetchall()]
        return awards, contracts


class ProcurementActivityReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, *, organization_code: str,
        period_from: date, period_to: date, company_number: str | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], set[str]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        params = {
            "organization_code": organization_code,
            "period_from": period_from, "period_to": period_to,
        }
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            notices = [dict(row) for row in connection.execute(
                _PROCUREMENT_ACTIVITY_NOTICES_QUERY, params,
            ).fetchall()]
            awards = [dict(row) for row in connection.execute(
                _PROCUREMENT_OUTCOME_AWARDS_QUERY, params,
            ).fetchall()]
            contracts = [dict(row) for row in connection.execute(
                _PROCUREMENT_ACTIVITY_CONTRACTS_QUERY, params,
            ).fetchall()]
            _enrich_procurement_classification(connection, contracts)
            participated_notice_ids: set[str] = set()
            if company_number:
                participated_notice_ids = {
                    str(row["bid_notice_id"]) for row in connection.execute(
                        _PROCUREMENT_ACTIVITY_COMPANY_PARTICIPATION_QUERY,
                        {**params, "company_number": company_number},
                    ).fetchall()
                }
        return notices, awards, contracts, participated_notice_ids


class CompanyParticipationReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def _read(self, catalog: RegistryCatalog, query: str, *, company_number: str,
              period_from: date, period_to: date) -> list[dict[str, Any]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            return [dict(row) for row in connection.execute(query, {
                "company_number": company_number, "period_from": period_from,
                "period_to": period_to,
            }).fetchall()]

    def find(self, catalog: RegistryCatalog, **kwargs: Any) -> list[dict[str, Any]]:
        return self._read(catalog, _COMPANY_PARTICIPATIONS_QUERY, **kwargs)

    def competitors(self, catalog: RegistryCatalog, **kwargs: Any) -> list[dict[str, Any]]:
        return self._read(catalog, _COMPANY_COMPETITORS_QUERY, **kwargs)


class BidNoticeParticipationReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, *, notice_number: str, notice_order: str,
    ) -> list[dict[str, Any]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            return [dict(row) for row in connection.execute(
                _BID_NOTICE_PARTICIPATIONS_QUERY,
                {"notice_number": notice_number, "notice_order": notice_order},
            ).fetchall()]


class ContractSupplierBatchReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, *, unified_contract_numbers: list[str],
    ) -> list[dict[str, Any]]:
        if not unified_contract_numbers:
            return []
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            return [dict(row) for row in connection.execute(
                _CONTRACT_SUPPLIERS_BATCH_QUERY,
                {"unified_contract_numbers": unified_contract_numbers},
            ).fetchall()]
