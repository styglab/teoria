"""A fresh domain processes documents before Ontology publication without local meanings."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

from teoria.features.semantic_modeling.goods_dictionary.ontology_contracts import expression_snapshot
from teoria.features.specification_processing.normalization.dictionary_incremental import update_standard_dictionary
from teoria.features.specification_processing.normalization import dictionary_alignment
from .test_dictionary_candidates import corpus
from .test_dictionary_incremental import ContextAPI, Catalog


async def test_new_api_collects_grounded_candidates_without_model_meaning_writes(tmp_path, monkeypatch):
    class API(ContextAPI):
        async def dictionary(self, operation_id, payload):
            result=await super().dictionary(operation_id,payload)
            return {**result,'operation_id':operation_id,'policy_version':'source_literal_v1',
                    'summary':{'approved':len(result['decisions']),'held':0,'proposed':0}}
        async def dictionary_meaning(self, method, path, payload=None):
            assert method=='GET' and path=='/snapshot', 'v2 must not write legacy meanings'
            return expression_snapshot([],[],[]).model_dump(mode='json')
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    api=API()
    data=corpus('허용하중');data['documents'][0]['relations']=[]
    request=SimpleNamespace(run_id='ontology_candidates_fixture',artifact_root=tmp_path.as_uri(),
        model='fixture',model_concurrency=2,model_timeout_seconds=600,dictionary_auto_approve=True,
        dictionary_baseline=None,dictionary_standard=None,dictionary_meaning_auto_approve=True,
        mode='standard_management',classification_code=None)
    runner=SimpleNamespace(generate=AsyncMock(side_effect=AssertionError('no local meaning model')))
    result=await update_standard_dictionary(request,data,{},api=api,repository=Catalog(None),runner=runner)
    assert result['status']=='proposed' and result['candidate_count']==2 and result['auto_applied'] is False
    runner.generate.assert_not_awaited()
    report=json.loads((tmp_path/'specification_processing/ontology_candidates_fixture/ontology_candidates.json').read_text())
    assert report['authority']=='suggestion' and report['auto_approve'] is False
    assert all(c['candidate']['evidence'] and c['source_context'] for c in report['candidates'])
    monkeypatch.setattr(dictionary_alignment,'GoodsAuthoringClient',lambda:api)
    aligned=await dictionary_alignment.align_dictionary(request,data,{},maintenance=result)
    assert aligned['meaning_alignment']['policy_version']=='published_ontology_expression_v2'
    assert aligned['meaning_summary']=={'unresolved':2}
    assert all('dictionary_concept_ref' not in a and 'ontology_concept_ref' not in a
               for a in aligned['meaning_alignment']['documents'][0]['attributes'])
