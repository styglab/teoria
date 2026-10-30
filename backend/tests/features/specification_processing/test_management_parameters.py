"""Operator defaults, bounded acquisition, freeze/replay and evaluation isolation."""
from datetime import date
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from pydantic import ValidationError
from teoria.features.specification_processing.management_parameters import StandardManagementParameters
from teoria.features.specification_processing.document_selection import select_specifications
from teoria.features.specification_processing.management_batch import split_documents

CODE='4321150102'


def params(tmp_path,**extra):
    return StandardManagementParameters.model_validate({'classification_code':CODE,
        'execution':{'run_id':'selection_fixture','artifact_root':tmp_path.as_uri()},**extra})


def test_operator_defaults_and_invalid_ranges(tmp_path):
    p=params(tmp_path)
    assert p.target_specifications==30 and p.selection.strategy=='latest'
    assert p.selection.lookback_days==365 and p.selection.max_notices_to_scan==300
    assert p.management.auto_apply and p.management.holdout_documents==5
    assert p.management.purpose=='dictionary_management' and not p.management.force_review
    for patch in [{'target_specifications':0},{'classification_code':'123'},
                  {'selection':{'date_from':'2026-10-02','date_to':'2026-10-01'}},
                  {'management':{'purpose':'quality_evaluation'}},
                  {'execution':{'artifact_root':'https://example.test/output'}}]:
        with pytest.raises(ValidationError):params(tmp_path,**patch)


@pytest.mark.parametrize('purpose',['dictionary_management','initial_dictionary','incremental_update'])
def test_management_has_one_process_and_accepts_old_names(tmp_path,purpose):
    p=params(tmp_path,management={'purpose':purpose})
    assert p.management.purpose=='dictionary_management'
    assert p.management.baseline_dictionary is None
    assert not p.management.force_review
    schema=type(p.management).model_json_schema()
    assert schema['properties']['purpose']['enum']==['dictionary_management','quality_evaluation']


def test_force_review_is_explicit_and_not_an_evaluation_option(tmp_path):
    assert params(tmp_path,management={'force_review':True}).management.force_review
    with pytest.raises(ValidationError):
        params(tmp_path,management={'purpose':'quality_evaluation','force_review':True,
            'baseline_dictionary':{'uri':'file:///snapshot.json','sha256':'0'*64}})


def notice(number,payload):
    return {'notice_number':number,'notice_order':'001','source_payload':payload,
            'notice_published_at':'2026-10-01','source_record_hash':'1'*64}


def attachment(number,name='규격서.pdf'):
    return {'ntceSpecDocUrl1':f'https://example.test/{number}.pdf','ntceSpecFileNm1':name}


async def test_missing_non_spec_duplicate_and_download_failure_do_not_count(tmp_path):
    rows=[notice('empty',{}),notice('other',attachment('other','공고문.pdf')),
          notice('broken',attachment('broken')),notice('a',attachment('a')),
          notice('duplicate',attachment('duplicate')),notice('b',attachment('b'))]
    repo=AsyncMock(return_value=rows)
    async def acquire(uri):
        if 'broken' in uri:raise OSError('unavailable')
        return b'%PDF-1.7 example '+(b'one' if 'duplicate' in uri or '/a.' in uri else b'two')
    result=await select_specifications.fn(params(tmp_path,target_specifications=3),repository=repo,acquire=acquire,today=date(2026,10,30))
    assert result['acquired_specifications']==2 and result['shortfall']==1
    assert result['notices_scanned']==6 and result['stop_reason']=='available_candidates_exhausted'
    assert result['exclusion_summary']=={'no_specification_candidate':2,'source_unavailable_or_invalid':1,'duplicate_content':1}
    assert repo.await_args.args==(CODE,date(2025,10,30),date(2026,10,31),300)
    for selected in result['selected']:
        data=Path(selected['source_uri'].removeprefix('file://')).read_bytes()
        assert hashlib.sha256(data).hexdigest()==selected['sha256']


async def test_replay_uses_the_frozen_list_and_rejects_changed_inputs(tmp_path):
    repo=AsyncMock(return_value=[notice('a',attachment('a'))]);acquire=AsyncMock(return_value=b'%PDF-1.7 example')
    p=params(tmp_path,target_specifications=1)
    result=await select_specifications.fn(p,repository=repo,acquire=acquire)
    assert result['stop_reason']=='target_reached'
    again=await select_specifications.fn(p,repository=AsyncMock(side_effect=AssertionError()),acquire=acquire)
    assert again==result
    acquire.assert_awaited_once()
    with pytest.raises(ValueError,match='another selection'):
        await select_specifications.fn(params(tmp_path,target_specifications=2),repository=repo,acquire=acquire)


async def test_explicit_input_files_need_no_notice_database_and_reject_html(tmp_path):
    p=params(tmp_path,target_specifications=2,documents=[
        {'document_id':'one','filename':'input.pdf','source_uri':'https://example.test/one'},
        {'document_id':'two','filename':'input.pdf','source_uri':'https://example.test/two'}])
    async def acquire(uri):return b'%PDF-1.7 example' if uri.endswith('one') else b'<html>login</html>'
    result=await select_specifications.fn(p,repository=AsyncMock(side_effect=AssertionError()),acquire=acquire)
    assert result['acquired_specifications']==1 and result['explicit_files_checked']==2
    assert result['notices_scanned'] is None


def test_holdout_keeps_a_notices_attachments_together_and_checks_minimum():
    docs=[{'document_id':f'd{i}','notice_number':f'n{i//2}','source':{'sha256':str(i)}} for i in range(12)]
    validation,development=split_documents(docs,3,5)
    assert len(validation)==4 and len(development)==8
    notices={d['notice_number'] for d in docs if d['document_id'] in validation}
    assert not any(d['notice_number'] in notices for d in docs if d['document_id'] in development)
    assert split_documents(docs[:4],3,5)==([],[d['document_id'] for d in docs[:4]])


async def test_flow_exposes_typed_defaults_and_preserves_legacy_manifest(tmp_path,monkeypatch):
    from teoria.features.specification_processing import flows,management_batch
    execute=AsyncMock(return_value='managed');monkeypatch.setattr(management_batch,'execute_management_batch',execute)
    assert await flows.standard_management_flow.fn(classification_code=CODE)=='managed'
    assert execute.await_args.args[0].target_specifications==30
    assert 'classification_code' in flows.standard_management_flow.parameters.properties
    with pytest.raises(ValueError,match='not both'):
        await flows.standard_management_flow.fn(manifest={'classification_code':CODE},classification_code=CODE)


async def test_multi_item_notice_is_not_assigned_one_classification_blindly(tmp_path):
    row=notice('mixed',attachment('mixed'));row['purchase_items']=[{'code':CODE},{'code':'4321150701'}]
    acquire=AsyncMock()
    result=await select_specifications.fn(params(tmp_path),repository=AsyncMock(return_value=[row]),acquire=acquire)
    assert result['acquired_specifications']==0
    assert result['exclusion_summary']=={'mixed_item_classifications':1}
    acquire.assert_not_awaited()


@pytest.mark.parametrize('count,holdout,auto_apply',[(12,3,True),(4,3,False)])
@pytest.mark.parametrize('force_review',[False,True])
async def test_preparation_splits_before_writes_and_disables_apply_when_insufficient(tmp_path,monkeypatch,count,holdout,auto_apply,force_review):
    from teoria.features.specification_processing import flows
    from teoria.features.specification_processing.management_batch import prepare_batch
    from teoria.features.specification_processing.storage.artifact_store import artifact_store
    p=params(tmp_path,management={'holdout_documents':holdout,'force_review':force_review})
    selection={'run_id':'selection_fixture','artifact_root':tmp_path.as_uri(),'selected':[]}
    async with artifact_store(tmp_path.as_uri()) as store:
        for i in range(count):
            data=b'%PDF-1.7 '+str(i).encode()
            ref=await store.put('input_'+str(i)+'.pdf',data)
            selection['selected'].append({'document_id':'d'+str(i),'notice_number':'n'+str(i),'filename':'input.pdf',
                'source_uri':ref.uri,'sha256':ref.sha256,'artifact':ref.model_dump()})
        await store.put('specification_processing/selection_fixture/document_selection.json',b'{}')
    async def extract(request,workspace):
        corpus={'classification_code':CODE,'documents':[{'document_id':d.document_id,'notice_number':d.notice_number,
            'source':{'sha256':d.sha256},'extraction_status':'extracted'} for d in request.documents], 'unavailable_documents':[]}
        raw=json.dumps(corpus).encode();Path(workspace,'extracted.json').write_bytes(raw)
        async with artifact_store(request.artifact_root) as store:
            ref=await store.put('specification_processing/'+request.run_id+'/extracted.json',raw)
        return ref.model_dump(),False
    monkeypatch.setattr(flows,'extract_documents',extract)
    result=await prepare_batch.fn(p,selection)
    assert result['status']=='ready'
    request=result['request']
    assert request['dictionary_meaning_auto_approve']==auto_apply
    if auto_apply:
        assert len(request['documents'])==count-holdout
        dev=json.loads(Path(request['extraction_checkpoint']['uri'].removeprefix('file://')).read_text())
        val=json.loads(Path(request['dictionary_validation_corpus'][0]['uri'].removeprefix('file://')).read_text())
        assert not {d['source']['sha256'] for d in dev['documents']} & {d['source']['sha256'] for d in val['documents']}
        evidence=json.loads(Path(request['dictionary_evidence_corpus'][0]['uri'].removeprefix('file://')).read_text())
        assert not {d['source']['sha256'] for d in evidence['documents']} & {d['source']['sha256'] for d in val['documents']}
    else:
        assert request['dictionary_validation_corpus']==[]
    assert request['dictionary_require_validation']
    assert request['dictionary_reconcile']==force_review
    assert result['summary']['purpose']=='dictionary_management'
    assert request['run_id']=='selection_fixture_apply'
