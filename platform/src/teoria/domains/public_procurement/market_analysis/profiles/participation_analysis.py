"""Observed bid participation metrics, separate from independent award records."""
from datetime import date, datetime, timedelta


def participation_analysis(rows: list[dict], *, period_from: date, period_to: date) -> dict:
    def bucket():
        return {'participants': set(), 'confirmed': set(), 'winners': set(),
                'awards': set(), 'collection': {}}

    total = bucket()
    years = {year: bucket() for year in range(period_from.year, (period_to - timedelta(days=1)).year + 1)}
    for row in rows:
        if row.get('activity_type') not in {'participation', 'award'}:
            continue
        when = row.get('activity_date')
        if isinstance(when, datetime):
            when = when.date()
        if not isinstance(when, date) or not period_from <= when < period_to:
            continue
        event = str(row['event_key'])
        company = str(row.get('company_number') or '')
        identity = (company, event)
        for target in (total, years.setdefault(when.year, bucket())):
            status = row.get('opening_collection_status') or 'unknown'
            previous = target['collection'].get(event)
            # Conservative if a synthetic or inconsistent row reports conflicting states.
            if previous is None or previous == 'complete':
                target['collection'][event] = status
            if row['activity_type'] == 'award':
                if company:
                    target['awards'].add(identity)
            else:
                target['participants'].add(identity)
                if row.get('result_confirmed'):
                    target['confirmed'].add(identity)
                    if row.get('participation_successful'):
                        target['winners'].add(identity)

    def metrics(value):
        statuses = list(value['collection'].values())
        status = ('collecting' if 'collecting' in statuses else
                  'failed' if 'failed' in statuses else
                  'unknown' if not statuses or 'unknown' in statuses else 'complete')
        n, d = len(value['winners']), len(value['confirmed'])
        observed = len(value['participants'])
        return {
            'participation_count': observed if observed or status == 'complete' else None,
            'observed_participation_count': observed,
            'result_confirmed_participation_count': d,
            'observed_award_count': n,
            'independent_award_event_count': len(value['awards']),
            'observed_success_rate': round(n / d, 6) if d else None,
            'success_rate_numerator': n, 'success_rate_denominator': d,
            'overall_success_rate': None,
            'collection_status': status,
            'collection_status_label': {'collecting': '수집 중', 'complete': '수집 완료',
                                        'failed': '수집 확인 필요', 'unknown': '수집 상태 미확인'}[status],
            'known_opening_event_count': len(statuses),
            'collected_opening_event_count': statuses.count('complete'),
        }
    return {
        'summary': metrics(total),
        'yearly_activity': [{'year': year, **metrics(value)} for year, value in sorted(years.items(), reverse=True)],
        'basis': {
            'event_identity': ['business_registration_number', 'notice_number', 'notice_order',
                               'bid_classification_number', 'rebid_number'],
            'year_basis': 'opening_at', 'timezone': 'Asia/Seoul',
            'participation_date_fallback': 'final_award_date_then_bid_at', 'award_date_fallback': 'final_award_date',
            'success_rate_scope': 'observed_result_confirmed_participations',
            'collection_scope': 'known_opening_events_in_profile',
            'maximum_opening_rank': 10,
            'retain_available_final_winner_regardless_of_rank': True,
            'all_participants_retained': False,
            'overall_participation_coverage': 'unknown',
        },
    }
