"""Semantic authoring must preserve authority, owner order and explicit approval policy."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from teoria.features.specification_processing.normalization.dictionary_candidates import submission_from_corpus
from teoria.features.specification_processing.normalization.dictionary_semantics import author_dictionary_meanings
from .test_dictionary_candidates import corpus


class API:
    def __init__(self):
        self.concepts=[]; self.mappings=[]; self.calls=[]

    async def resolve_dictionary_meanings(self, ids, classification_code=None):
        items=[]
        for entry in ids:
            mappings=[m for m in self.mappings if m['source_entry_id']==entry and m['status']=='approved']
            if mappings:
                target=next(c for c in self.concepts if c['revision_id']==mappings[0]['target_revision_id'])
                items.append({'status':'resolved','concept_id':target['concept_id'],'reason':'approved'})
            else:items.append({'status':'unresolved','reason':'no_mapping'})
        return {'items':items}

    async def dictionary_meaning(self, method, path, payload=None):
        self.calls.append((method,path,deepcopy(payload)))
        if method=='GET':return {'items':deepcopy(self.concepts)}
        if path=='/concepts':
            row={'revision_id':str(UUID(int=len(self.concepts)+100)), 'concept_id':str(UUID(int=len(self.concepts)+200)),
                 'concept_key':payload['key'],'content':payload,'status':'draft'}
            self.concepts.append(row);return deepcopy(row)
        if path=='/mappings':
            row={**payload,'mapping_id':str(UUID(int=len(self.mappings)+300)),'status':'draft'}
            self.mappings.append(row);return deepcopy(row)
        kind,id,_=path.strip('/').split('/')
        rows=self.concepts if kind=='concept' else self.mappings
        key='revision_id' if kind=='concept' else 'mapping_id'
        row=next(r for r in rows if r[key]==id);row['status']='approved';return deepcopy(row)


class Runner:
    def __init__(self, *, reject=False, bad_quote=False, target=None):
        self.calls=[];self.reject=reject;self.bad_quote=bad_quote;self.target=target

    async def generate(self, instruction, context, output, **kwargs):
        self.calls.append(context)
        if 'proposal' in context:
            return {**{k:not self.reject for k in ['source_supported','unambiguous','same_meaning','definition_supported']},
                    'rationale':'원문과 대상 및 속성의 의미를 재검증한 결과입니다.'}
        candidate=context['occurrences'][0]['candidate']
        definition={'key':'mobile_table' if candidate['kind']=='item_type' else 'mobile_table_load',
            'kind':candidate['kind'],'preferred_name':candidate['preferred_name'],
            'definition':'원문에 명시된 이동형 진료대 또는 그 허용하중을 나타내는 로컬 정의입니다.',
            'references':['source:provided']}
        if candidate['kind']=='characteristic':
            definition.update(value_kind='number',applicable_item_type_ids=[context['owner_concept_id']],
                quantity_dimension='mass',canonical_unit='kg',allowed_units=['kg'])
        return {'action':'equivalent' if self.target else 'create','target_revision_id':self.target,
                'definition':None if self.target else definition,'rationale':'원문 근거와 적용 대상이 일치하여 정의 및 연결합니다.',
                'evidence_quote':'invented' if self.bad_quote else candidate['evidence'][0]['quote']}


def setup(auto=True, mode='standard_management'):
    original=corpus('허용하중');submission=submission_from_corpus(original)
    registration={'decisions':[{'candidate_key':c.candidate_key,'entry_id':str(UUID(int=i+1)),'status':'approved'}
                              for i,c in enumerate(submission.candidates)]}
    request=SimpleNamespace(mode=mode,dictionary_standard=None,dictionary_meaning_auto_approve=auto,model='fixture',
                            model_concurrency=1,model_timeout_seconds=10,classification_code=None)
    return request,original,submission,registration


async def test_auto_approval_creates_owner_before_property_and_reuses_approved_meanings():
    args=setup();api=API();runner=Runner()
    report=await author_dictionary_meanings(*args,api,runner=runner)
    assert report['summary']=={'approved':2}
    assert len(runner.calls)==4
    assert all(c['status']=='approved' for c in api.concepts)
    assert api.concepts[1]['content']['applicable_item_type_ids']==[api.concepts[0]['concept_id']]
    assert all(m['classification_code'] is None for m in api.mappings)
    assert all(c['content']['references'][0].startswith('source:40c6') for c in api.concepts)
    before=len(runner.calls)
    repeat=await author_dictionary_meanings(*args,api,runner=runner)
    assert repeat['summary']=={'reused':2} and len(runner.calls)==before


async def test_proposal_only_does_not_approve_definition_or_map_to_draft_owner():
    api=API();report=await author_dictionary_meanings(*setup(False),api,runner=Runner())
    assert report['summary']=={'proposed':1,'held':1}
    assert api.concepts[0]['status']=='draft' and not api.mappings
    assert not any('/decisions' in path for _,path,_ in api.calls)


@pytest.mark.parametrize('runner',[Runner(reject=True),Runner(bad_quote=True)])
async def test_failed_semantic_or_grounding_check_never_writes(runner):
    api=API();report=await author_dictionary_meanings(*setup(),api,runner=runner)
    assert report['summary']=={'held':2}
    assert not any(method=='POST' for method,_,_ in api.calls)


async def test_fixed_document_processing_never_calls_model_or_meaning_write_api():
    api=API();runner=Runner()
    report=await author_dictionary_meanings(*setup(mode='document_processing'),api,runner=runner)
    assert report['status']=='skipped_fixed_standard' and not api.calls and not runner.calls


async def test_unapproved_target_cannot_be_mapped_even_when_model_claims_equivalence():
    api=API();report=await author_dictionary_meanings(*setup(),api,runner=Runner(target=str(UUID(int=100))))
    assert report['summary']=={'held':2} and not api.concepts


async def test_existing_approved_definition_is_mapped_without_creating_a_revision():
    args=setup();api=API()
    await author_dictionary_meanings(*args,api,runner=Runner())
    api.mappings.clear();before=deepcopy(api.concepts)

    class ExistingRunner(Runner):
        async def generate(self, instruction, context, output, **kwargs):
            if 'proposal' not in context:
                kind=context['occurrences'][0]['candidate']['kind']
                self.target=next(c['revision_id'] for c in api.concepts if c['content']['kind']==kind)
            return await super().generate(instruction,context,output,**kwargs)

    report=await author_dictionary_meanings(*args,api,runner=ExistingRunner())
    assert report['summary']=={'approved':2} and api.concepts==before
    assert all(m['status']=='approved' for m in api.mappings)


async def test_incompatible_unit_policy_is_held_before_writing_property():
    class WrongUnitRunner(Runner):
        async def generate(self, instruction, context, output, **kwargs):
            result=await super().generate(instruction,context,output,**kwargs)
            if result.get('definition',{}).get('kind')=='characteristic':
                result['definition'].update(canonical_unit='kW',allowed_units=['kW'])
            return result

    api=API();report=await author_dictionary_meanings(*setup(),api,runner=WrongUnitRunner())
    assert report['summary']=={'approved':1,'held':1}
    assert len(api.concepts)==len(api.mappings)==1


async def test_admin_http_client_preserves_authenticated_dictionary_write_boundary():
    import httpx
    from teoria.features.specification_processing.authoring_client import GoodsAuthoringClient

    def handler(request):
        assert request.url.path=='/v1/admin/goods/dictionary/concept/revision/decisions'
        assert request.headers['authorization']=='Bearer fixture-token'
        return httpx.Response(200,json={'status':'approved'})

    async with GoodsAuthoringClient(base_url='http://admin.invalid',token='fixture-token',
                                    transport=httpx.MockTransport(handler)) as api:
        result=await api.dictionary_meaning('POST','/concept/revision/decisions',
                                          {'action':'approve','rationale':'정책 검증을 통과한 자동 승인입니다.'})
    assert result=={'status':'approved'}


async def test_stage_06_applies_newly_approved_meanings_in_the_same_run(tmp_path,monkeypatch):
    from teoria.features.specification_processing.normalization import dictionary_alignment, dictionary_semantics
    args=setup();request,original,submission,registration=args
    original['documents'][0]['relations']=[]
    request.run_id='meaning_fixture';request.artifact_root=tmp_path.as_uri();request.dictionary_auto_approve=True

    class StageAPI(API):
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def dictionary(self,operation_id,payload):
            return {**registration,'operation_id':operation_id,'policy_version':'source_literal_v1',
                    'summary':{'approved':2,'held':0,'proposed':0}}
        async def resolve_dictionary_meanings(self,ids,classification_code=None):
            result=await super().resolve_dictionary_meanings(ids,classification_code)
            for entry,row in zip(ids,result['items']):
                row['source_entry_id']=entry
                if row['status']=='resolved':
                    mapping=next(m for m in self.mappings if m['source_entry_id']==entry and m['status']=='approved')
                    concept=next(c for c in self.concepts if c['revision_id']==mapping['target_revision_id'])
                    row.update(revision_id=concept['revision_id'],mapping_ids=[mapping['mapping_id']],definition=concept['content'])
            return result

    api=StageAPI()
    monkeypatch.setattr(dictionary_alignment,'GoodsAuthoringClient',lambda:api)
    monkeypatch.setattr(dictionary_semantics,'CodexRunner',lambda **kwargs:Runner())
    result=await dictionary_alignment.align_dictionary(request,original,{'sha256':'a'*64})
    assert result['meaning_summary']=={'resolved':2}
    attr=result['meaning_alignment']['documents'][0]['attributes'][0]
    assert attr['meaning_status']=='resolved' and attr['typed_value']=={'decimal':'200','unit':'kg'}
    assert attr['value_raw']=='200' and 'characteristic_ref' not in attr
    assert result['summary']['semantic_authoring']=={'approved':2}
    assert (tmp_path/'specification_processing/meaning_fixture/dictionary_semantic_decisions.json').exists()


def test_semantic_context_includes_owner_scope_text_and_source_ancestors():
    from teoria.features.specification_processing.normalization.dictionary_semantics import observation_context
    original=corpus('허용하중')
    doc=original['documents'][0]
    doc['parsed_document']['nodes'].insert(0,{'node_id':'heading','text':'이동형 진료대의 규격','parent_id':None})
    doc['parsed_document']['nodes'][-1]['parent_id']='heading'
    doc['attributes'][0]['resolution_evidence_node_ids']=['heading','detail']
    candidates=submission_from_corpus(original).candidates
    context=observation_context(original,[candidates[-1]])[0]
    assert context['owners'][0]['name']=='이동형 진료대'
    texts={n['node_id']:n['text'] for n in context['source_context']}
    assert texts['heading']=='이동형 진료대의 규격' and '200kg' in texts['detail']
