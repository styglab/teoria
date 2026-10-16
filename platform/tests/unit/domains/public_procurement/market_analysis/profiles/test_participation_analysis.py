from datetime import date

from teoria.domains.public_procurement.market_analysis.profiles.participation_analysis import (
    participation_analysis,
)


def row(kind, event, *, company='company', status='complete', confirmed=True, successful=False, when=date(2024, 2, 1)):
    return dict(activity_type=kind, event_key=event, company_number=company,
                opening_collection_status=status, result_confirmed=confirmed,
                participation_successful=successful, activity_date=when)


def analyze(rows):
    return participation_analysis(rows, period_from=date(2022, 1, 1), period_to=date(2025, 1, 1))


def test_same_participation_cohort_is_used_for_rate_not_independent_awards():
    rows = [row('participation', 'N:000:1:0', successful=True),
            row('participation', 'N:000:1:0', successful=True),  # repeated source row
            row('participation', 'N:000:2:0'),  # distinct lot on the same notice
            row('participation', 'N:000:2:1', confirmed=False, successful=True),
            row('award', 'N:000:1:0'), row('award', 'OTHER:000:1:0')]
    summary = analyze(rows)['summary']
    assert summary['observed_participation_count'] == 3
    assert summary['result_confirmed_participation_count'] == 2
    assert summary['observed_award_count'] == 1
    assert summary['independent_award_event_count'] == 2
    assert summary['observed_success_rate'] == .5
    assert summary['overall_success_rate'] is None


def test_missing_participation_in_queued_year_is_collecting_not_zero_participation():
    result = analyze([row('award', 'OLD:000:1:0', status='collecting', when=date(2022, 6, 1))])
    year = next(y for y in result['yearly_activity'] if y['year'] == 2022)
    assert year['collection_status'] == 'collecting'
    assert year['collection_status_label'] == '수집 중'
    assert year['participation_count'] is None
    assert year['observed_participation_count'] == 0
    assert year['observed_success_rate'] is None
    assert year['independent_award_event_count'] == 1


def test_complete_retained_scope_does_not_claim_complete_population():
    result = analyze([row('participation', 'N:000:1:0', successful=True)])
    assert result['summary']['collection_status'] == 'complete'
    assert result['summary']['overall_success_rate'] is None
    assert result['basis']['maximum_opening_rank'] == 10
    assert result['basis']['retain_available_final_winner_regardless_of_rank'] is True
    assert result['basis']['all_participants_retained'] is False


def test_unknown_failed_and_out_of_period_records_are_not_reported_as_complete():
    result = analyze([row('participation', 'A', status=None), row('award', 'B', status='failed'),
                      row('participation', 'C', when=date(2025, 1, 1))])
    assert result['summary']['collection_status'] == 'failed'
    assert result['summary']['observed_participation_count'] == 1
    assert result['summary']['collected_opening_event_count'] == 0
