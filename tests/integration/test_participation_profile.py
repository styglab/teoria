"""Real DB checks for opening cohorts and the Runtime collection projection."""
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest

from teoria.domains.public_procurement.market_analysis.sql.profiles import _PROCUREMENT_PROFILE_ACTIVITIES_QUERY
from teoria.domains.public_procurement.market_analysis.profiles.participation_analysis import participation_analysis
from teoria_pipelines.persistence import PostgresStore

DATABASE_URL = os.environ.get('TEORIA_TEST_DATA_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='TEORIA_TEST_DATA_DATABASE_URL is not set')


@pytest.fixture(scope='module', autouse=True)
def migrated_database():
    PostgresStore(DATABASE_URL).apply_migrations(Path(__file__).parents[2] / 'pipelines/database/migrations')


def test_opening_cohort_preserves_lots_and_only_confirmed_winners_enter_rate():
    notice = 'test_' + uuid4().hex
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
        # Roll back the synthetic records even when assertions fail.
        with c.transaction(force_rollback=True):
            c.execute("INSERT INTO public_procurement.bid_notices (notice_number,notice_order,work_type,notice_published_at,demand_organization_code,source_record_hash,source_payload) VALUES (%s,'000','service','2023-12-30','test_org','notice_hash','{}'::jsonb)", (notice,))
            for lot, winner in [('1','1000000001'), ('2','1000000002'), ('3',None), ('4','1000000002'), ('5','1000000001')]:
                c.execute("INSERT INTO public_procurement.bid_awards (notice_number,notice_order,bid_classification_number,rebid_number,work_type,winner_business_registration_number,opening_at,final_award_date,demand_organization_code,source_record_hash) VALUES (%s,'000',%s,'0','service',%s,'2024-01-01T00:30:00+09:00','2025-01-02','test_org','award_hash')", (notice,lot,winner))
                c.execute("INSERT INTO public_procurement.bid_opening_participants (notice_number,notice_order,bid_classification_number,rebid_number,business_registration_number,opening_rank,bid_at,source_record_hash) VALUES (%s,'000',%s,'0','1000000001',%s,'2024-01-02','participant_hash')", (notice,lot,11 if lot=='4' else 15 if lot=='5' else 5))
                c.execute("INSERT INTO ingestion.bid_opening_enrichment_queue (notice_number,notice_order,bid_classification_number,rebid_number,award_source_record_hash,status) VALUES (%s,'000',%s,'0','award_hash','pending')", (notice,lot))
            rows = c.execute(_PROCUREMENT_PROFILE_ACTIVITIES_QUERY, dict(organization_code=None,company_numbers=['1000000001'],period_from=date(2024,1,1),period_to=date(2025,1,1))).fetchall()
            rows = [dict(r) for r in rows if r['bid_notice_id'] == notice + ':000']
            assert len([r for r in rows if r['activity_type']=='participation']) == 4
            assert {r['activity_date'] for r in rows} == {date(2024,1,1)}
            summary = participation_analysis(rows, period_from=date(2024,1,1),period_to=date(2025,1,1))['summary']
            assert summary['observed_participation_count'] == 4
            assert summary['result_confirmed_participation_count'] == 3
            assert summary['observed_award_count'] == 2
            assert summary['observed_success_rate'] == .666667
            assert summary['independent_award_event_count'] == 2
            assert summary['collection_status'] == 'collecting'


def test_runtime_can_read_collection_projection_without_ingestion_access():
    with psycopg.connect(DATABASE_URL) as c:
        with c.transaction(force_rollback=True):
            c.execute('SET LOCAL ROLE teoria_runtime')
            assert c.execute("SELECT has_schema_privilege(current_user,'ingestion','USAGE')").fetchone()[0] is False
            c.execute('SELECT * FROM public_procurement.runtime_bid_opening_collection_status LIMIT 1')
