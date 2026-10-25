from copy import deepcopy
from uuid import UUID
import pytest
from teoria.features.goods_normalization.contracts import checksum
from teoria.features.goods_normalization.candidates.semantic_resolution import MeaningBatch, validate_decisions


def example():
    uid=lambda n:str(UUID(int=n))
    ontology={'objects':[{'business_object_id':uid(10),'concept_id':uid(1),'stable_key':'test.memory',
        'properties':[{'concept_id':uid(2),'stable_key':'test.memory.capacity','value_type':'decimal','unit':'GB'}]}], 'relationships':[]}
    group={'group_id':'a'*64,'context':{'kind':'requirement','source_kind':'capacity','label':'capacity',
        'target_concept_ids':[uid(1)],'unresolved_targets':[],'role':'requirement_candidate',
        'scope':'per_module','value_type':'number','unit':'GB'},'decision':'new_concept_review',
        'observations':[{'source_text':'모듈당 메모리 64GB 이상'}]}
    batch={'decisions':[{'group_id':'a'*64,'action':'existing','reason':'same memory capacity',
        'concept_id':uid(2),'units':[{'source_unit':'GB','canonical_unit':'GB'}],
        'citations':[{'observation_index':0,'quote':'64GB 이상'}]}]}
    return ontology,{'groups':[group]},batch


def test_existing_semantic_decision_preserves_scope_and_explicit_units():
    ontology,report,data=example()
    batch=MeaningBatch.model_validate(data)
    assert validate_decisions(batch,report,ontology)==batch
    assert report['groups'][0]['context']['scope']=='per_module'


@pytest.mark.parametrize('change',['citation','owner','direction','unit','new_unit','unresolved'])
def test_invalid_model_proposal_is_held_without_becoming_a_mapping(change):
    ontology,report,data=example();decision=data['decisions'][0]
    if change=='citation':decision['citations'][0]['quote']='128GB'
    if change=='owner':report['groups'][0]['context']['target_concept_ids']=[str(UUID(int=99))]
    if change=='direction':decision['reverse']=True
    if change=='unit':decision['units']=[{'source_unit':'TB','canonical_unit':'GB','multiplier':'1000'}]
    if change=='new_unit':
        decision.update(action='new',concept_id=None,new_concept={'code':'other_capacity','name':'Capacity',
            'description':'Memory capacity','value_type':'decimal','unit':'TB'},
            units=[{'source_unit':'GB','canonical_unit':'TB','multiplier':'0.001'}])
    if change=='unresolved':report['groups'][0]['decision']='hold'
    result=validate_decisions(MeaningBatch.model_validate(data),report,ontology)
    assert result.decisions[0].action=='hold'
    assert result.decisions[0].concept_id is None and not result.decisions[0].units


def test_missing_or_duplicate_groups_fail_the_batch():
    ontology,report,data=example()
    for decisions in [[],data['decisions']*2]:
        with pytest.raises(ValueError,match='exactly once'):
            validate_decisions(MeaningBatch.model_validate({'decisions':decisions}),report,ontology)


async def test_automatic_approval_is_explicit_and_evaluation_scoped(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from teoria.features.goods_normalization.candidates.semantic_workflow import run_semantic_cycle
    repo=AsyncMock()
    repo._candidate_context.return_value=(SimpleNamespace(ontology=SimpleNamespace(namespace='goods')), {})
    model=AsyncMock()
    monkeypatch.setattr('teoria.features.goods_normalization.candidates.semantic_workflow.resolve_meanings',model)
    with pytest.raises(ValueError,match='evaluation'):
        await run_semantic_cycle(repo,UUID(int=1),[],model='test',version='2',actor='principal:test',auto_approve=True)
    model.assert_not_awaited()
    repo.transition.assert_not_awaited()


async def test_model_hold_never_creates_or_approves_drafts(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from teoria.features.goods_normalization.candidates.semantic_workflow import run_semantic_cycle
    repo=AsyncMock()
    repo._candidate_context.return_value=(SimpleNamespace(ontology=SimpleNamespace(namespace='goods_eval_test')), {})
    model=AsyncMock(return_value={'decisions':[{'action':'hold'}]})
    monkeypatch.setattr('teoria.features.goods_normalization.candidates.semantic_workflow.resolve_meanings',model)
    result=await run_semantic_cycle(repo,UUID(int=1),[],model='test',version='2',actor='principal:test',auto_approve=True)
    assert result['status']=='held' and not result['auto_approved']
    repo.transition.assert_not_awaited()


async def test_published_projection_hides_authoring_status_and_omitted_groups_are_held(monkeypatch):
    from teoria.features.goods_normalization.contracts import NormalizationProfile
    from teoria.features.goods_normalization.contracts.candidates import CandidateBundle,CandidateContext
    from teoria.features.goods_normalization.candidates.semantic_resolution import resolve_meanings
    uid=lambda n:str(UUID(int=n))
    ontology={'namespace':'test','version':'1','objects':[{'business_object_id':uid(10),'concept_id':uid(1),
        'stable_key':'test.memory','name':'Memory','status':'draft','created_by':'internal:author',
        'properties':[]}],'relationships':[]}
    profile=NormalizationProfile.model_validate({'profile_key':'test','version':'1','classification_code':'4321150102',
        'ontology':{'version_id':uid(100),'namespace':'test','version':'1','checksum':checksum(ontology)},
        'entities':[{'rule_id':'memory','aliases':['RAM'],'concept_id':uid(1)}]})
    context=CandidateContext(kind='entity',label='주기억장치',source_kind='equipment')
    group={'group_id':checksum(context),'context':context.model_dump(mode='json'),'aliases':['주기억장치'],
        'observations':[{'document_id':'synthetic','source_sha256':'a'*64,'local_id':'e1',
            'evidence':[{'node_id':'n'}],'source_text':'주기억장치 64GB 이상','grounded':True,'raw':{'name':'주기억장치'}}]}
    body={'schema_version':1,'artifact_kind':'goods_meaning_candidates','classification_code':profile.classification_code,
        'ontology':profile.ontology.model_dump(mode='json'),'groups':[group]}
    bundle=CandidateBundle.model_validate({**body,'checksum':checksum(body)})
    async def model(self,instruction,context,output,**kwargs):
        assert context['ontology']['publication_status']=='published'
        assert all('status' not in c and 'created_by' not in c for c in context['concepts'])
        assert 'output_schema' in kwargs
        return {'decisions':[]}
    monkeypatch.setattr('teoria.integrations.codex.CodexRunner.generate',model)
    result=await resolve_meanings([bundle],profile,ontology,model='test_model')
    assert len(result['decisions'])==1 and result['decisions'][0]['action']=='hold'
    assert 'omitted' in result['decisions'][0]['reason']


def test_dimension_text_with_unit_is_not_approved_as_a_unitless_string():
    ontology,report,data=example()
    context=report['groups'][0]['context'];context.update(value_type='text',unit='mm')
    report['groups'][0]['observations'][0]['source_text']='880 x 448 x 176 mm'
    decision=data['decisions'][0]
    decision.update(action='new',concept_id=None,new_concept={'code':'dimensions','name':'Dimensions',
        'description':'Physical dimensions','value_type':'string','unit':None},units=[],
        citations=[{'observation_index':0,'quote':'880 x 448 x 176 mm'}])
    result=validate_decisions(MeaningBatch.model_validate(data),report,ontology)
    assert result.decisions[0].action=='hold'
