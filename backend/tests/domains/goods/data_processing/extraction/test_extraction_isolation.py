from copy import deepcopy
from types import SimpleNamespace
import pytest
from teoria.domains.goods.data_processing.extraction.extraction_validation import isolate_extraction_failures,validate_checkpoint,reproduce_attribute_validation


def corpus_fixture():
    text='11. 프로그램: 100개 저장'
    def document(id):
        return {'document_id':id,'notice_number':None,'source':{'sha256':id[0]*64},
          'classification_code':None,'parsed_document':{'nodes':[{'node_id':'n','text':text,'native_ref':'/page/2'}]},
          'parser':{'version':'fixture'},'entities':[{'id':'root','name':'프로그램','kind':'software','evidence':[{'node_id':'n','quote':'프로그램'}]}],
          'relations':[],'requirements':[],'declared_quantities':[],'attributes':[{
             'id':id+'_count','subject_ids':['root'],'property_key':'program_storage_count','value_raw':'100','unit_raw':'개',
             'operator':'eq','data_type':'number','evidence':{'node_id':'n'},'semantic_role':'requirement_candidate','semantic_scope':'per_item'}],
          'extraction_status':'extracted','unresolved_extraction':{}}
    docs=[document('a_doc'),document('b_doc')]
    return {'classification_code':None,'documents':docs,'unavailable_documents':[]},SimpleNamespace(classification_code=None),[{'document_id':d['document_id'],'source':d['source']} for d in docs]


def test_bad_numeric_observation_is_preserved_for_review_and_normal_documents_survive():
    corpus,request,sources=corpus_fixture()
    bad=deepcopy(corpus['documents'][0]['attributes'][0]);bad.update(id='bad_count',value_raw='10')
    corpus['documents'][0]['attributes'].append(bad)
    result=isolate_extraction_failures(corpus,request,sources)
    assert len(result['documents'])==2 and result['unavailable_documents']==[]
    assert [a['id'] for a in result['documents'][0]['attributes']]==['a_doc_count']
    document=result['documents'][0]
    assert document['extraction_status']=='partial'
    assert document['quarantined_attributes'][0]['attribute']==bad
    assert document['validation_issues'][0]['code']=='source_numeric_literal_mismatch'
    validate_checkpoint(result,request,sources)
    assert reproduce_attribute_validation(document,'bad_count')['code']=='source_numeric_literal_mismatch'
    assert reproduce_attribute_validation(document,'a_doc_count')['verdict']=='valid'
    assert len(corpus['documents'][0]['attributes'])==2


def test_document_graph_failure_is_isolated_but_source_hash_corruption_is_fatal():
    corpus,request,sources=corpus_fixture()
    corpus['documents'][0]['relations']=[{'source_id':'root','target_id':'missing','kind':'component_of'}]
    result=isolate_extraction_failures(corpus,request,sources)
    assert [d['document_id'] for d in result['documents']]==['b_doc']
    assert result['unavailable_documents'][0]['code']=='document_validation_failed'
    corpus['documents'][0]['source']={'sha256':'f'*64}
    with pytest.raises(ValueError,match='source mismatch'):isolate_extraction_failures(corpus,request,sources)


def test_duplicate_ids_are_all_quarantined_and_schema_errors_are_not_hidden():
    corpus,request,sources=corpus_fixture()
    corpus['documents'][0]['attributes']*=2
    result=isolate_extraction_failures(corpus,request,sources)
    assert not result['documents'][0]['attributes']
    assert len(result['documents'][0]['quarantined_attributes'])==2
    corpus['documents'][0]['attributes'][0].pop('id')
    with pytest.raises(KeyError):isolate_extraction_failures(corpus,request,sources)
