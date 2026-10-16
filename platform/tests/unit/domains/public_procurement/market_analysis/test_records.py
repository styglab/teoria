from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from teoria.domains.public_procurement.market_analysis.participation.models import (
    participation_row,
)
from teoria.domains.public_procurement.market_analysis.profiles.models import (
    profile_activity_row,
)
from teoria.domains.public_procurement.market_analysis.row_validation import (
    MarketDataError,
)


def profile():
    return {'activity_type':'contract','event_key':'event-1','activity_date':date(2026,10,12),
            'event_amount':Decimal('123.45'),'attributed_contract_amount':None,
            'amount_completeness':'unknown','source_detail':'preserved'}


def test_profile_contract_keeps_decimal_null_and_additional_source_fields():
    raw = profile()
    assert profile_activity_row(raw) is raw
    assert raw['attributed_contract_amount'] is None
    assert raw['event_amount'] == Decimal('123.45')
    assert raw['source_detail'] == 'preserved'


@pytest.mark.parametrize('field,value', [('event_amount',123.45), ('activity_date','2026-10-12'),
                                         ('activity_type','unknown_stage'), ('amount_completeness','guessed')])
def test_profile_contract_rejects_inconsistent_types_without_echoing_values(field, value):
    raw = profile()
    raw[field] = value
    with pytest.raises(MarketDataError) as exc:
        profile_activity_row(raw)
    assert field in str(exc.value)
    assert str(value) not in str(exc.value)


def test_profile_contract_does_not_silently_default_missing_amount():
    raw = profile()
    del raw['event_amount']
    with pytest.raises(MarketDataError, match='event_amount:missing'):
        profile_activity_row(raw)


def test_participation_contract_preserves_unknown_result_and_amount():
    timestamp = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)
    raw = {'bid_notice_id':'notice:000','participation_date':timestamp, 'rank':None,
           'participant_count':None,'bid_amount':None,'winning_amount':None,'result':None}
    assert participation_row(raw) is raw
    assert raw['participation_date'] is timestamp
    raw['rank'] = '1'
    with pytest.raises(MarketDataError, match='rank:int_type'):
        participation_row(raw)
