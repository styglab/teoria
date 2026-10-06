from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row


def validate_procurement_shadow(database_url: str, bid_notice_id: str) -> dict[str, Any]:
    notice_number, separator, notice_order = bid_notice_id.rpartition(":")
    if not separator or not notice_number or not notice_order:
        raise ValueError("bid_notice_id must use '<notice_number>:<notice_order>'")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        notice = connection.execute(
            """SELECT notice_number||':'||notice_order AS computed_id,notice_name
                 FROM public_procurement.bid_notices
                WHERE notice_number=%s AND notice_order=%s""",
            (notice_number, notice_order),
        ).fetchone()
        if notice is None:
            raise LookupError(bid_notice_id)
        participation = connection.execute(
            """SELECT count(*) AS event_count,
                      count(DISTINCT participation_id) AS distinct_event_count,
                      bool_and(participation_id = notice_number||':'||notice_order||':'||
                        bid_classification_number||':'||rebid_number||':'||business_registration_number)
                        AS identity_matches,
                      count(DISTINCT notice_number||':'||notice_order||':'||
                        bid_classification_number||':'||rebid_number) AS lot_count
                 FROM public_procurement.bid_opening_participants
                WHERE notice_number=%s AND notice_order=%s""",
            (notice_number, notice_order),
        ).fetchone()
        awards = connection.execute(
            """SELECT count(*) AS event_count,count(DISTINCT award_id) AS distinct_event_count,
                      bool_and(award_id=notice_number||':'||notice_order||':'||
                        bid_classification_number||':'||rebid_number) AS identity_matches
                 FROM public_procurement.bid_awards
                WHERE notice_number=%s AND notice_order=%s""",
            (notice_number, notice_order),
        ).fetchone()
        contracts = connection.execute(
            """WITH raw AS (
                   SELECT c.*,
                          CASE WHEN c.notice_number ~ '^[0-9]{13}$' AND right(c.notice_number,2)='00'
                               THEN left(c.notice_number,length(c.notice_number)-2)
                               ELSE NULLIF(c.notice_number,'') END AS normalized_notice
                     FROM public_procurement.contracts c
                ), versions AS (
                   SELECT raw.*,
                          CASE WHEN long_term_continuation_type LIKE '장기%%'
                                     AND normalized_notice IS NOT NULL
                                     AND NULLIF(btrim(contract_name),'') IS NOT NULL
                               THEN concat('long_term:',normalized_notice,':',md5(btrim(contract_name)))
                               ELSE COALESCE(NULLIF(confirmed_contract_number,''),
                                             NULLIF(contract_reference_number,''),unified_contract_number)
                           END AS event_id
                     FROM raw WHERE normalized_notice=%s
                ), ranked AS (
                   SELECT versions.*,row_number() OVER (
                            PARTITION BY event_id ORDER BY concluded_date DESC NULLS LAST,
                              updated_at DESC,unified_contract_number DESC) AS position
                     FROM versions
                )
                SELECT count(*) AS version_count,count(DISTINCT event_id) AS event_count,
                       count(*) FILTER (WHERE position=1) AS selected_version_count
                  FROM ranked""",
            (notice_number,),
        ).fetchone()
        parties = connection.execute(
            """SELECT count(*) AS party_count,
                      count(*) FILTER (WHERE business_registration_number IS NOT NULL) AS identified_party_count,
                      count(*) FILTER (WHERE participation_share_rate IS NOT NULL) AS known_share_count
                 FROM public_procurement.contract_suppliers s
                 JOIN public_procurement.contracts c USING (unified_contract_number)
                WHERE CASE WHEN c.notice_number ~ '^[0-9]{13}$' AND right(c.notice_number,2)='00'
                           THEN left(c.notice_number,length(c.notice_number)-2)
                           ELSE NULLIF(c.notice_number,'') END=%s""",
            (notice_number,),
        ).fetchone()
    evaluated_checks = {
        "bid_notice_identity": notice["computed_id"] == bid_notice_id,
        "participation_identity_unique": (
            participation["event_count"] == participation["distinct_event_count"]
            if participation["event_count"] else None
        ),
        "participation_identity_matches": (
            participation["identity_matches"] if participation["event_count"] else None
        ),
        "award_identity_unique": (
            awards["event_count"] == awards["distinct_event_count"]
            if awards["event_count"] else None
        ),
        "award_identity_matches": awards["identity_matches"] if awards["event_count"] else None,
        "contract_latest_version_one_per_event": (
            contracts["event_count"] == contracts["selected_version_count"]
            if contracts["event_count"] else None
        ),
    }
    failed = any(value is False for value in evaluated_checks.values())
    not_evaluated = [key for key, value in evaluated_checks.items() if value is None]
    return {
        "status": "failed" if failed else "partial" if not_evaluated else "passed",
        "bid_notice_id": bid_notice_id,
        "notice_name": notice["notice_name"],
        "checks": evaluated_checks,
        "not_evaluated": not_evaluated,
        "completeness_reason": (
            "no_linked_participation_award_or_contract_rows"
            if len(not_evaluated) == 5 else None
        ),
        "observations": {
            "procurement_lot_count": participation["lot_count"],
            "participation_event_count": participation["event_count"],
            "award_event_count": awards["event_count"],
            "contract_version_count": contracts["version_count"],
            "contract_event_count": contracts["event_count"],
            "contract_party_count": parties["party_count"],
            "identified_contract_party_count": parties["identified_party_count"],
            "known_share_party_count": parties["known_share_count"],
        },
    }
