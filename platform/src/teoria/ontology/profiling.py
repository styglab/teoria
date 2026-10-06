from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class ProfileQuery:
    key: str
    sql: str
    deep: bool = False


PROFILE_QUERIES = (
    ProfileQuery(
        "population",
        """
        SELECT
          (SELECT count(*) FROM public_procurement.bid_notices) AS bid_notice_count,
          (SELECT count(*) FROM public_procurement.bid_awards) AS award_count,
          (SELECT count(*) FROM public_procurement.bid_opening_participants) AS participation_count,
          (SELECT count(*) FROM public_procurement.contracts) AS contract_snapshot_count,
          (SELECT count(*) FROM public_procurement.contract_suppliers) AS contract_party_row_count
        """,
    ),
    ProfileQuery(
        "notice_classification",
        """
        SELECT count(*) AS total,
          count(*) FILTER (WHERE procurement_classification_number IS NOT NULL) AS classified,
          count(*) FILTER (WHERE procurement_classification_number IS NULL) AS unclassified
        FROM public_procurement.bid_notices
        """,
    ),
    ProfileQuery(
        "notice_lineage",
        """
        SELECT count(*) AS total,
          count(*) FILTER (WHERE is_re_notice) AS re_notice_count,
          count(*) FILTER (WHERE is_re_notice AND previous_notice_number IS NOT NULL) AS re_notice_with_previous,
          count(*) FILTER (WHERE is_re_notice AND lineage_root_notice_number IS NOT NULL) AS re_notice_with_root
        FROM public_procurement.bid_notices
        """,
    ),
    ProfileQuery(
        "award_linkage",
        """
        SELECT count(*) AS total,
          count(*) FILTER (WHERE a.winner_business_registration_number IS NOT NULL) AS identified_winner,
          count(*) FILTER (WHERE n.notice_number IS NOT NULL) AS linked_notice
        FROM public_procurement.bid_awards a
        LEFT JOIN public_procurement.bid_notices n
          ON n.notice_number=a.notice_number AND n.notice_order=a.notice_order
        """,
    ),
    ProfileQuery(
        "participation_linkage",
        """
        SELECT count(*) AS total,
          count(*) FILTER (WHERE p.business_registration_number IS NOT NULL) AS identified_company,
          count(*) FILTER (WHERE n.notice_number IS NOT NULL) AS linked_notice
        FROM public_procurement.bid_opening_participants p
        LEFT JOIN public_procurement.bid_notices n
          ON n.notice_number=p.notice_number AND n.notice_order=p.notice_order
        """,
    ),
    ProfileQuery(
        "contract_shape",
        """
        SELECT count(*) AS total,
          count(*) FILTER (WHERE notice_number IS NOT NULL AND length(btrim(notice_number)) > 0) AS with_notice_number,
          count(*) FILTER (WHERE procurement_classification_number IS NOT NULL) AS classified,
          count(*) FILTER (WHERE is_joint_contract) AS joint_contract
        FROM public_procurement.contracts
        """,
    ),
    ProfileQuery(
        "contract_party_completeness",
        """
        SELECT count(*) AS party_rows,
          count(DISTINCT unified_contract_number) AS contracts_with_party,
          count(*) FILTER (WHERE business_registration_number IS NOT NULL) AS identified_party_rows,
          count(*) FILTER (WHERE participation_share_rate IS NOT NULL) AS known_share_rows
        FROM public_procurement.contract_suppliers
        """,
    ),
    ProfileQuery(
        "raw_provenance",
        """
        SELECT
          (SELECT count(*) FROM ingestion.raw_provider_observations) AS observation_count,
          (SELECT count(*) FROM ingestion.raw_provider_payloads) AS payload_count,
          (SELECT count(*) FROM public_procurement.bid_notices WHERE source_record_hash IS NOT NULL) AS notices_with_hash,
          (SELECT count(*) FROM public_procurement.bid_awards WHERE source_record_hash IS NOT NULL) AS awards_with_hash,
          (SELECT count(*) FROM public_procurement.contracts WHERE source_record_hash IS NOT NULL) AS contracts_with_hash
        """,
    ),
    ProfileQuery(
        "contract_notice_linkage",
        """
        WITH notice_numbers AS MATERIALIZED (
          SELECT DISTINCT notice_number FROM public_procurement.bid_notices
        )
        SELECT count(*) AS contracts_with_notice_number,
          count(n.notice_number) AS linked_by_notice_number
        FROM public_procurement.contracts c
        LEFT JOIN notice_numbers n ON n.notice_number=c.notice_number
        WHERE c.notice_number IS NOT NULL AND length(btrim(c.notice_number)) > 0
        """,
        deep=True,
    ),
    ProfileQuery(
        "business_name_collisions",
        """
        WITH names AS (
          SELECT business_registration_number AS company_number, supplier_name AS company_name
          FROM public_procurement.contract_suppliers
          UNION ALL
          SELECT winner_business_registration_number, winner_name FROM public_procurement.bid_awards
          UNION ALL
          SELECT business_registration_number, participant_name FROM public_procurement.bid_opening_participants
        ), normalized AS (
          SELECT company_number, lower(regexp_replace(company_name, '\\s+', '', 'g')) AS normalized_name
          FROM names WHERE company_number IS NOT NULL AND company_name IS NOT NULL
        )
        SELECT count(*) AS company_numbers_with_multiple_names
        FROM (SELECT company_number FROM normalized GROUP BY company_number HAVING count(DISTINCT normalized_name)>1) c
        """,
        deep=True,
    ),
)


def run_ontology_profile(
    database_url: str,
    *,
    include_deep: bool = False,
    statement_timeout_ms: int = 30_000,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        connection.read_only = True
        connection.execute("SELECT set_config('statement_timeout', %s, false)", (str(statement_timeout_ms),))
        connection.commit()
        for query in PROFILE_QUERIES:
            if query.deep and not include_deep:
                results[query.key] = {"status": "skipped", "reason": "deep_profile_not_requested"}
                continue
            try:
                with connection.transaction():
                    row = connection.execute(query.sql).fetchone()
                results[query.key] = {"status": "available", "values": _json_values(row or {})}
            except psycopg.errors.QueryCanceled:
                connection.rollback()
                results[query.key] = {
                    "status": "unavailable",
                    "reason": "statement_timeout",
                    "statement_timeout_ms": statement_timeout_ms,
                }
            except psycopg.Error as exc:
                connection.rollback()
                results[query.key] = {
                    "status": "unavailable",
                    "reason": "database_error",
                    "sqlstate": exc.sqlstate,
                }
    return {
        "profile_version": "ontology-source-profile-v1",
        "mode": "deep" if include_deep else "quick",
        "statement_timeout_ms": statement_timeout_ms,
        "results": results,
        "limitations": [
            "contracts is a current snapshot table; contract version history cannot be measured from it",
            "business-registration to corporate-registration resolution is stored outside the procurement data DB",
            "source_record_hash presence does not alone prove end-to-end raw payload linkage",
        ],
    }


def _json_values(row: dict[str, Any]) -> dict[str, Any]:
    return {key: float(value) if isinstance(value, Decimal) else value for key, value in row.items()}
