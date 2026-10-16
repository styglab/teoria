"""Data DB statements owned by this market-analysis feature."""

_COMPANY_PARTICIPATIONS_QUERY = """
SELECT p.bid_notice_id,p.notice_name,
       p.demand_organization_code AS organization_code,
       p.demand_organization_name AS organization_name,
       p.participation_date,p.rank,p.participant_count,p.bid_amount,p.winning_amount,
       p.result,p.result_confirmed,p.work_type,p.field_code,p.field_name,
       p.large_category,p.middle_category,p.classification_source,p.participant_name
FROM public_procurement.runtime_bid_opening_participants p
WHERE p.business_registration_number=%(company_number)s
  AND p.participation_date >= %(period_from)s
  AND p.participation_date < %(period_to)s
"""


_BID_NOTICE_PARTICIPATIONS_QUERY = """
SELECT a.bid_notice_id,a.notice_name,a.bid_classification_number,a.rebid_number,
       a.participant_count AS source_participant_count,
       a.winner_business_registration_number,
       p.participation_id,p.business_registration_number,p.participant_name,
       p.opening_rank,p.bid_amount,p.bid_rate,p.result,p.result_confirmed
FROM public_procurement.runtime_bid_awards a
LEFT JOIN public_procurement.runtime_bid_opening_participants p
  ON p.notice_number=a.notice_number AND p.notice_order=a.notice_order
 AND p.bid_classification_number=a.bid_classification_number
 AND p.rebid_number=a.rebid_number
WHERE a.notice_number=%(notice_number)s AND a.notice_order=%(notice_order)s
ORDER BY a.bid_classification_number,a.rebid_number,p.opening_rank NULLS LAST,
         p.business_registration_number NULLS LAST,p.participation_id NULLS LAST
"""


_COMPANY_COMPETITORS_QUERY = """
SELECT co.business_registration_number AS company_number,
       co.participant_name AS company_name,
       co.bid_notice_id,co.participation_date,
       concat_ws(':',co.notice_number,co.notice_order,
                 co.bid_classification_number,co.rebid_number) AS participation_event_id,
       target.work_type,target.field_code,target.field_name,
       target.large_category,target.middle_category,target.classification_source
FROM public_procurement.runtime_bid_opening_participants target
JOIN public_procurement.runtime_bid_opening_participants co
  ON co.notice_number=target.notice_number AND co.notice_order=target.notice_order
 AND co.bid_classification_number=target.bid_classification_number
 AND co.rebid_number=target.rebid_number
WHERE target.business_registration_number=%(company_number)s
  AND co.business_registration_number<>%(company_number)s
  AND target.participation_date >= %(period_from)s
  AND target.participation_date < %(period_to)s
"""
