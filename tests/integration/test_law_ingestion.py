import os
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from teoria_pipelines.domains.legal_information.laws.models import LawTarget, LawVersion, LawResponse, LawCatalog
from teoria_pipelines.domains.legal_information.laws.parsing import parse_law
from teoria_pipelines.domains.legal_information.laws.repository import LawRepository
from teoria_pipelines.models import CollectionWindow
from teoria_pipelines.persistence import PostgresStore

DATABASE_URL=os.environ.get('TEORIA_TEST_DATA_DATABASE_URL')
pytestmark=pytest.mark.skipif(not DATABASE_URL,reason='TEORIA_TEST_DATA_DATABASE_URL is not set')
ROOT=Path(__file__).parents[2]


@pytest.fixture
def law_setup():
    store=PostgresStore(DATABASE_URL or '')
    store.apply_migrations(ROOT/'pipelines/database/migrations')
    run_id=uuid4();store.start_run(run_id,'law_test',CollectionWindow(date(2026,7,1),date(2026,7,1)))
    law_id=str(10000000+uuid4().int%10000000)
    target=LawTarget(id='test_'+uuid4().hex,name='테스트 법률',law_id=law_id)
    v=LawVersion(law_id,'100',date(2026,7,1),'테스트 법률',date(2026,1,1),'999','일부개정',{'현행연혁코드':'현행'})
    raw=(ROOT/'pipelines/tests/fixtures/legal_information/law_body.xml').read_bytes().replace(b'000001',law_id.encode())
    r=LawResponse('get_law_version',{'MST':'100','efYd':'20260701'},datetime.now(timezone.utc),'text/xml',raw)
    repo=LawRepository(DATABASE_URL or '')
    repo.register_catalog(target,LawCatalog(law_id,[v],[]))
    return repo,run_id,target,v,r


def test_snapshots_deduplicate_and_changed_source_keeps_previous_content(law_setup):
    repo,run,target,v,r=law_setup
    source_hash=repo.save_raw(run,r);parsed=parse_law(r.raw_body,v)
    first=repo.save_snapshot(parsed,r,source_hash)
    assert repo.save_snapshot(parsed,r,source_hash)==first
    changed=replace(r,raw_body=r.raw_body.replace('첫 번째 목'.encode(),'변경된 목'.encode()),fetched_at=datetime.now(timezone.utc))
    changed_hash=repo.save_raw(run,changed)
    second=repo.save_snapshot(parse_law(changed.raw_body,v),changed,changed_hash)
    assert first!=second
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute('SELECT count(*) FROM legal_information.law_snapshot WHERE law_id=%s',(v.law_id,)).fetchone()[0]==2
        assert c.execute("SELECT content FROM legal_information.law_provision WHERE snapshot_id=%s AND kind='item'",(first,)).fetchone()[0]=='첫 번째 목'
        assert c.execute('SELECT latest_snapshot_id FROM legal_information.law_version WHERE law_id=%s',(v.law_id,)).fetchone()[0]==second
    rows=repo.get_provisions(v.law_id,v.mst,v.effective_date,'24의2')
    assert len(rows)==5
    assert next(p['content'] for p in rows if p['kind']=='item')=='변경된 목'
    assert repo.archived_response(repo.stored_versions(target.id)[0]).raw_body==changed.raw_body


def test_failed_structural_write_rolls_back_snapshot_and_pointer(law_setup):
    repo,run,target,v,r=law_setup
    source_hash=repo.save_raw(run,r);parsed=parse_law(r.raw_body,v)
    parsed.provisions[1]['parent_path']='missing_parent'
    with pytest.raises(psycopg.errors.ForeignKeyViolation): repo.save_snapshot(parsed,r,source_hash)
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute('SELECT count(*) FROM legal_information.law_snapshot WHERE law_id=%s',(v.law_id,)).fetchone()[0]==0
        assert c.execute('SELECT latest_snapshot_id FROM legal_information.law_version WHERE law_id=%s',(v.law_id,)).fetchone()[0] is None


def test_reparse_new_parser_uses_archive_and_preserves_old_revision(law_setup):
    repo,run,target,v,r=law_setup
    h=repo.save_raw(run,r);parsed=parse_law(r.raw_body,v)
    old=repo.save_snapshot(parsed,r,h)
    archived=repo.archived_response(repo.stored_versions(target.id)[0])
    reparsed=parse_law(archived.raw_body,v);reparsed.parser_version='test_new_parser'
    new=repo.save_snapshot(reparsed,archived,h)
    assert old!=new
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute('SELECT count(*) FROM legal_information.law_snapshot WHERE law_id=%s',(v.law_id,)).fetchone()[0]==2
    assert repo.stored_versions(target.id)[0]['parser_version']=='test_new_parser'


def test_incremental_collection_keeps_new_historical_and_future_slices(law_setup):
    repo,run,target,v,r=law_setup
    repo.save_snapshot(parse_law(r.raw_body,v),r,repo.save_raw(run,r))
    historical=replace(v,listing={'현행연혁코드':'연혁'})
    new=replace(v,mst='90',effective_date=date(2025,1,1),listing={'현행연혁코드':'연혁'})
    future=replace(v,effective_date=date(2027,1,1),listing={'현행연혁코드':'시행예정'})
    catalog=LawCatalog(v.law_id,[historical,new,future],[])
    repo.register_catalog(target,catalog)
    selected=repo.select_versions(catalog,reconcile_all=False,today=date(2026,10,12))
    assert [v.key for v in selected]==[new.key,future.key]
    assert len(repo.select_versions(catalog,reconcile_all=True,today=date(2026,10,12)))==3


def test_runtime_has_no_law_archive_access(law_setup):
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute("SELECT has_table_privilege('teoria_runtime','legal_information.law_snapshot','SELECT')").fetchone()[0] is False
        assert c.execute("SELECT has_table_privilege('teoria_runtime','legal_information.law_search_documents','SELECT')").fetchone()[0] is True
        assert c.execute("SELECT has_table_privilege('teoria_runtime','ingestion.law_raw_payloads','SELECT')").fetchone()[0] is False


def test_provision_lookup_preserves_numeric_sibling_order(law_setup):
    repo,run,target,v,r=law_setup
    extra=''.join(f'<호><호번호>{i}.</호번호><호내용>순서 {i}</호내용></호>' for i in range(2,13)).encode()
    raw=r.raw_body.replace(b'</'+ '항'.encode()+b'>', extra+b'</'+ '항'.encode()+b'>',1)
    r=replace(r,raw_body=raw)
    repo.save_snapshot(parse_law(raw,v),r,repo.save_raw(run,r))
    rows=repo.get_provisions(v.law_id,v.mst,v.effective_date,'24의2')
    assert [p['number'] for p in rows if p['kind']=='subparagraph']==[f'{i}.' for i in range(1,13)]


def test_keyword_search_finds_descendants_and_pins_old_snapshot(law_setup):
    from teoria.domains.legal_information.search import LawSearchReader, LawSearchRequest
    repo,run,target,v,r=law_setup
    r=replace(r,raw_body=r.raw_body.replace('첫 번째 목'.encode(),'고유검색문구'.encode()))
    first=repo.save_snapshot(parse_law(r.raw_body,v),r,repo.save_raw(run,r))
    reader=LawSearchReader(DATABASE_URL)
    result=reader.search(LawSearchRequest(query='고유검색문구',match='all',law_id=v.law_id,assessment_date=date(2026,7,1)))
    assert result['items'][0]['number']=='24의2'
    assert result['items'][0]['snapshot_id']==first
    assert result['legal_applicability_confirmed'] is False
    path=result['items'][0]['path']
    changed=replace(r,raw_body=r.raw_body.replace('고유검색문구'.encode(),'변경된 목'.encode()),fetched_at=datetime.now(timezone.utc))
    second=repo.save_snapshot(parse_law(changed.raw_body,v),changed,repo.save_raw(run,changed))
    assert reader.search(LawSearchRequest(query='고유검색문구',match='all',law_id=v.law_id))['items']==[]
    assert '고유검색문구' in reader.get_document(first,path)['content']
    assert '변경된 목' in reader.get_document(second,path)['content']


def test_keyword_search_does_not_mix_future_versions_or_treat_wildcards_as_query(law_setup):
    from teoria.domains.legal_information.search import LawSearchReader, LawSearchRequest
    repo,run,target,v,r=law_setup
    repo.save_snapshot(parse_law(r.raw_body,v),r,repo.save_raw(run,r))
    future=replace(v,mst='101',effective_date=date(2027,1,1))
    repo.register_catalog(target,LawCatalog(v.law_id,[v,future],[]))
    future_r=replace(r,query={'MST':'101','efYd':'20270101'},raw_body=r.raw_body.replace(b'20260701',b'20270101'),fetched_at=datetime.now(timezone.utc))
    repo.save_snapshot(parse_law(future_r.raw_body,future),future_r,repo.save_raw(run,future_r))
    reader=LawSearchReader(DATABASE_URL)
    hits=reader.search(LawSearchRequest(query='테스트',law_id=v.law_id,assessment_date=date(2026,10,12)))['items']
    assert hits and {h['mst'] for h in hits}=={'100'}
    hits=reader.search(LawSearchRequest(query='테스트',law_id=v.law_id,version_scope='all'))['items']
    assert {h['mst'] for h in hits}=={'100','101'}
    assert reader.search(LawSearchRequest(query='_%',law_id=v.law_id))['items']==[]


def test_repeal_does_not_resurrect_earlier_version(law_setup):
    from teoria.domains.legal_information.search import LawSearchReader, LawSearchRequest
    repo,run,target,v,r=law_setup
    repo.save_snapshot(parse_law(r.raw_body,v),r,repo.save_raw(run,r))
    repeal=replace(v,mst='102',effective_date=date(2026,10,1),amendment_type='폐지')
    repo.register_catalog(target,LawCatalog(v.law_id,[v,repeal],[]))
    repeal_r=replace(r,query={'MST':'102','efYd':'20261001'},raw_body=r.raw_body.replace(b'20260701',b'20261001'))
    repo.save_snapshot(parse_law(repeal_r.raw_body,repeal),repeal_r,repo.save_raw(run,repeal_r))
    reader=LawSearchReader(DATABASE_URL)
    assert reader.search(LawSearchRequest(query='테스트',law_id=v.law_id,assessment_date=date(2026,10,12)))['items']==[]
    assert reader.search(LawSearchRequest(query='테스트',law_id=v.law_id,assessment_date=date(2026,9,30)))['items']


def test_keyword_search_reports_missing_new_version_instead_of_falling_back(law_setup):
    from teoria.domains.legal_information.search import LawSearchReader, LawSearchRequest
    repo,run,target,v,r=law_setup
    repo.save_snapshot(parse_law(r.raw_body,v),r,repo.save_raw(run,r))
    newer=replace(v,mst='103',effective_date=date(2026,10,1))
    repo.register_catalog(target,LawCatalog(v.law_id,[v,newer],[]))
    result=LawSearchReader(DATABASE_URL).search(LawSearchRequest(query='테스트',law_id=v.law_id,assessment_date=date(2026,10,12)))
    assert result['items']==[]
    assert result['unavailable_versions'][0]['mst']=='103'


def test_runtime_role_reads_search_projection_without_base_tables(law_setup):
    repo,run,target,v,r=law_setup
    repo.save_snapshot(parse_law(r.raw_body,v),r,repo.save_raw(run,r))
    with psycopg.connect(DATABASE_URL) as c:
        c.execute('SET ROLE teoria_runtime')
        assert c.execute('SELECT count(*) FROM legal_information.law_search_documents WHERE law_id=%s',(v.law_id,)).fetchone()[0]>0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute('SELECT * FROM legal_information.law_snapshot LIMIT 1')
