"""Run only against an explicitly provisioned, disposable catalog test database."""
import os
from datetime import date
import pytest
from teoria.features.specification_processing.catalog.repository import DocumentCatalogRepository
from teoria.integrations.data_operations.persistence.connection import connect

URL=os.environ.get('TEORIA_TEST_CATALOG_DATABASE_URL')
pytestmark=pytest.mark.skipif(not URL,reason='isolated catalog database required')

async def test_catalog_versions_retry_retention_filters_and_empty_pages():
    async with connect(URL) as conn:
        for run,sha,classification,notice,day,status in [
            ('old','a','4321150102','n',1,'completed'),
            ('retry','a','4321150102','n',2,'failed'),
            ('new_version','b','4321150102','n',3,'completed'),
            ('other_notice','a','4321150102','other',4,'completed'),
            ('unclassified','c',None,None,5,'running')]:
            await conn.execute("INSERT INTO public_procurement.specification_processing_runs(run_id,input_fingerprint,mode,classification_code,artifact_root,status,started_at) VALUES (%s,%s,'document_processing',%s,'s3://test',%s,%s)",[run,'f'*64,classification,status,f'2026-10-0{day}'])
            await conn.execute("INSERT INTO public_procurement.specification_processing_inputs(run_id,document_id,filename,source_sha256,notice_number) VALUES (%s,'doc','서버.pdf',%s,%s)",[run,sha*64,notice])
            if status!='running':
                await conn.execute("INSERT INTO public_procurement.specification_processing_documents VALUES (%s,'doc',%s,%s,%s,'{}')",[run,notice,'extracted',sha*64])
                await conn.execute("INSERT INTO public_procurement.specification_processing_artifacts VALUES (%s,%s,'s3://test/ref',%s,1,'application/json')",[run,f'specification_processing/{run}/extracted.json','f'*64])
    repo=DocumentCatalogRepository(URL)
    rows=await repo.documents(classification='4321150102')
    assert rows['total']==3
    retained=next(row for row in rows['items'] if row['attempt_count']==2)
    assert retained['run_id']=='old' and retained['latest_run_id']=='retry' and retained['result_available']
    assert (await repo.history(retained['catalog_id']))['total']==2
    assert (await repo.entry(retained['catalog_id']))['run_id']=='old'
    assert (await repo.documents(status='failed'))['total']==1
    assert (await repo.documents(classification='unclassified'))['total']==1
    assert (await repo.documents(query='서버',since=date(2026,10,3)))['total']==3
    assert (await repo.documents(offset=100))=={'items':[],'total':4}
    assert (await repo.classifications())['documents']==4
    assert len(await repo.index_runs(100))==4
