"""Opt-in real SQL lifecycle; only TEORIA_TEST_APP_DATABASE_URL is used."""
from copy import deepcopy
import os
from pathlib import Path
from uuid import UUID,uuid4
import pytest
from teoria.persistence import apply_migrations
from teoria.ontology.authoring import OntologyAuthoringRepository
from teoria.domains.goods.normalization.repository import NormalizationProfileRepository
from teoria_goods_normalization import NormalizationProfile

DATABASE_URL=os.environ.get('TEORIA_TEST_APP_DATABASE_URL')
pytestmark=pytest.mark.skipif(not DATABASE_URL,reason='isolated Application DB required')


async def test_real_profile_approval_export_and_immutable_history():
    await apply_migrations(DATABASE_URL,Path(__file__).parents[2]/'database/migrations')
    ontology=OntologyAuthoringRepository(DATABASE_URL);namespace='test_norm_'+uuid4().hex
    version=await ontology.create_ontology(namespace=namespace,name='Test memory',description='Synthetic test only',version='1.0',actor='test:owner')
    vid=UUID(version['ontology_version_id'])
    obj=await ontology.add_item(vid,kind='object',payload={'code':'memory','name':'Memory','stable_key':namespace+'.memory'},actor='test:owner')
    prop=await ontology.add_item(vid,kind='property',payload={'code':'capacity','name':'Capacity','stable_key':namespace+'.memory.capacity','object_concept_id':obj['concept_id'],'value_type':'decimal','unit':'GB'},actor='test:owner')
    await ontology.transition(vid,action='submit',actor='test:owner');await ontology.transition(vid,action='approve',actor='test:reviewer')
    published=await ontology.publish(vid,actor='test:publisher')
    template={'profile_key':'test_'+uuid4().hex,'version':'1','classification_code':'4321150102',
        'entities':[{'rule_id':'memory','aliases':['RAM'],'concept_id':namespace+'.memory'}],
        'requirements':[{'rule_id':'capacity','target_concept_id':namespace+'.memory','property_concept_id':namespace+'.memory.capacity',
            'source_property_keys':['capacity'],'roles':['requirement_candidate'],'scopes':['per_module'],'value_type':'number',
            'units':[{'source_unit':'GB','canonical_unit':'GB'}]}]}
    profiles=NormalizationProfileRepository(DATABASE_URL)
    draft=await profiles.create_from_template(vid,template,actor='test:creator');rid=UUID(draft['revision_id'])
    assert draft['status']=='draft' and draft['content']['ontology']['checksum']==published['artifact']['checksum']
    with pytest.raises(ValueError,match='approved'):await profiles.export(rid)
    changed=deepcopy(draft['content']);changed['entities'][0]['aliases'].append('메모리')
    await profiles.update(rid,NormalizationProfile.model_validate(changed),actor='test:editor')
    await profiles.transition(rid,action='submit',actor='test:owner')
    with pytest.raises(ValueError,match='draft'):await profiles.update(rid,NormalizationProfile.model_validate(changed),actor='test:editor')
    await profiles.transition(rid,action='approve',actor='test:reviewer')
    exported=await profiles.export(rid)
    assert exported.approval_actor=='test:reviewer'
    assert str(exported.profile.requirements[0].property_concept_id)==prop['concept_id']
    assert exported==await profiles.export(rid)
    with pytest.raises(ValueError,match='draft'):await profiles.update(rid,NormalizationProfile.model_validate(changed),actor='test:editor')
    assert [e['action'] for e in await profiles.audit(rid)]==['created','updated','submit','approve']
    # Candidate ingestion reuses the same persisted profile lifecycle and audit table.
    from teoria_goods_normalization import checksum
    from teoria_goods_normalization.candidates import CandidateBundle, CandidateContext
    from teoria.domains.goods.normalization.candidate_proposals import CandidateSelection
    context=CandidateContext(kind='entity',label='Memory',source_kind='equipment')
    group={'group_id':checksum(context),'context':context.model_dump(mode='json'),'aliases':['Memory'],
        'observations':[{'document_id':'synthetic','source_sha256':'a'*64,'local_id':'e1',
            'evidence':[{'node_id':'n1','quote':'Memory'}],'source_text':'Memory','grounded':True,'raw':{'name':'Memory'}}]}
    body={'schema_version':1,'artifact_kind':'goods_meaning_candidates',
        'classification_code':exported.profile.classification_code,
        'ontology':exported.profile.ontology.model_dump(mode='json'),'groups':[group]}
    bundle=CandidateBundle.model_validate({**body,'checksum':checksum(body)})
    report=await profiles.candidate_proposals(rid,[bundle,bundle])
    assert report['groups'][0]['observation_count']==1
    selected=[CandidateSelection(group_id=group['group_id'],concept_id=obj['concept_id'])]
    candidate_draft=await profiles.create_from_candidates(rid,[bundle],selected,version='2',actor='test:candidate_author')
    candidate_id=UUID(candidate_draft['revision_id'])
    assert candidate_draft['status']=='draft'
    assert candidate_draft['content']['entities'][-1]['aliases']==['Memory']
    import json
    provenance=json.loads((await profiles.audit(candidate_id))[0]['comment'])
    assert provenance['proposal_checksum']==report['checksum']
    assert (await profiles.audit(candidate_id))[0]['actor']=='test:candidate_author'
    with pytest.raises(ValueError,match='approved'):await profiles.export(candidate_id)
    await profiles.transition(candidate_id,action='submit',actor='test:candidate_author')
    await profiles.transition(candidate_id,action='approve',actor='test:reviewer')
    assert (await profiles.export(candidate_id)).profile.version=='2'
    assert (await profiles.export(rid)).profile.version=='1'
    await profiles.transition(rid,action='deprecate',actor='test:owner')
    with pytest.raises(ValueError,match='approved'):await profiles.export(rid)


async def test_supplied_goods_extensions_and_template_use_the_existing_ontology_workflow():
    from teoria.ontology.blueprint import OntologyBlueprint,apply_ontology_blueprint
    from teoria.ontology.enrichment import OntologyEnrichmentManifest,apply_ontology_enrichment
    from teoria.ontology.extension import OntologyExtensionManifest,apply_ontology_extension
    import json
    root=Path(__file__).parents[3];namespace='test_goods_'+uuid4().hex
    await apply_migrations(DATABASE_URL,root/'platform/database/migrations')
    repo=OntologyAuthoringRepository(DATABASE_URL)
    blueprint=OntologyBlueprint.load(root/'platform/ontology_blueprints/goods.yaml')
    blueprint.namespace=namespace
    for obj in blueprint.objects:
        obj.stable_key=obj.stable_key.replace('goods.',namespace+'.',1)
        for prop in obj.properties:prop.stable_key=prop.stable_key.replace('goods.',namespace+'.',1)
    for rel in blueprint.relationships:rel.stable_key=rel.stable_key.replace('goods.',namespace+'.',1)
    initial=await apply_ontology_blueprint(repo,blueprint,actor='test:owner');initial_id=UUID(initial['ontology_version_id'])
    await repo.transition(initial_id,action='submit',actor='test:owner');await repo.transition(initial_id,action='approve',actor='test:owner');await repo.publish(initial_id,actor='test:owner')
    enrichment=OntologyEnrichmentManifest.load(root/'platform/ontology_blueprints/goods_requirement_enrichment.yaml')
    enrichment.ontologies[0].namespace=namespace
    for prop in enrichment.ontologies[0].properties:prop.stable_key=prop.stable_key.replace('goods.',namespace+'.',1)
    await apply_ontology_enrichment(repo,enrichment,actor='test:owner',publish=False)
    extension=OntologyExtensionManifest.load(root/'platform/ontology_blueprints/goods_memory_extension.yaml');extension.ontology_namespace=namespace
    for obj in extension.objects:
        obj.stable_key=obj.stable_key.replace('goods.',namespace+'.',1)
        for prop in obj.properties:prop.stable_key=prop.stable_key.replace('goods.',namespace+'.',1)
    for rel in extension.relationships:rel.stable_key=rel.stable_key.replace('goods.',namespace+'.',1)
    await apply_ontology_extension(repo,extension,actor='test:owner')
    updated=next(v for v in await repo.list_versions(namespace) if v['version']=='0.2.0');vid=UUID(updated['ontology_version_id'])
    await repo.transition(vid,action='submit',actor='test:owner');await repo.transition(vid,action='approve',actor='test:owner');await repo.publish(vid,actor='test:owner')
    template=json.loads((root/'docs/procurement_specification_processing/examples/server_memory_profile.json').read_text().replace('goods.',namespace+'.'))
    template['profile_key']='test_'+uuid4().hex
    profiles=NormalizationProfileRepository(DATABASE_URL);draft=await profiles.create_from_template(vid,template,actor='test:owner');rid=UUID(draft['revision_id'])
    await profiles.transition(rid,action='submit',actor='test:owner');await profiles.transition(rid,action='approve',actor='test:owner')
    exported=await profiles.export(rid)
    assert len(exported.profile.requirements)==3 and len(exported.profile.relations)==1
    assert (await repo.get_version(initial_id))['status']=='deprecated'


async def test_semantic_workflow_creates_and_auto_approves_new_concepts_in_isolated_db(monkeypatch):
    from teoria_goods_normalization import checksum
    from teoria_goods_normalization.candidates import CandidateBundle,CandidateContext
    from teoria.domains.goods.normalization.semantic_workflow import run_semantic_cycle
    await apply_migrations(DATABASE_URL,Path(__file__).parents[2]/'database/migrations')
    authoring=OntologyAuthoringRepository(DATABASE_URL);namespace='goods_eval_'+uuid4().hex
    version=await authoring.create_ontology(namespace=namespace,name='Synthetic semantic evaluation',description='Isolated test',version='1',actor='test:owner')
    vid=UUID(version['ontology_version_id'])
    memory=await authoring.add_item(vid,kind='object',payload={'code':'memory','name':'Memory','stable_key':namespace+'.memory'},actor='test:owner')
    server=await authoring.add_item(vid,kind='object',payload={'code':'server','name':'Server','stable_key':namespace+'.server'},actor='test:owner')
    await authoring.transition(vid,action='submit',actor='test:owner');await authoring.transition(vid,action='approve',actor='test:owner');await authoring.publish(vid,actor='test:owner')
    profiles=NormalizationProfileRepository(DATABASE_URL)
    base=await profiles.create_from_template(vid,{'profile_key':'test_'+uuid4().hex,'version':'1','classification_code':'4321150102',
        'entities':[{'rule_id':'memory','aliases':['RAM'],'concept_id':namespace+'.memory'},
            {'rule_id':'server','aliases':['Server'],'concept_id':namespace+'.server'}]},actor='test:owner')
    rid=UUID(base['revision_id']);await profiles.transition(rid,action='submit',actor='test:owner');await profiles.transition(rid,action='approve',actor='test:owner')
    profile=(await profiles.export(rid)).profile
    contexts=[CandidateContext(kind='entity',label='CPU',source_kind='equipment'),
        CandidateContext(kind='requirement',label='frequency',source_kind='frequency',target_concept_ids=[memory['concept_id']],
            role='requirement_candidate',scope='per_component',value_type='number',unit='GHz'),
        CandidateContext(kind='relation',label='component_of',source_kind='component_of',
            source_concept_id=memory['concept_id'],destination_concept_id=server['concept_id'])]
    groups=[]
    for i,context in enumerate(contexts):
        groups.append({'group_id':checksum(context),'context':context.model_dump(mode='json'),'aliases':[context.label],
            'observations':[{'document_id':'synthetic','source_sha256':'a'*64,'local_id':str(i),
                'evidence':[{'node_id':'n'}],'source_text':'Server contains RAM; CPU; RAM frequency 3GHz','grounded':True,'raw':{'name':context.label}}]})
    body={'schema_version':1,'artifact_kind':'goods_meaning_candidates','classification_code':profile.classification_code,
        'ontology':profile.ontology.model_dump(mode='json'),'groups':groups}
    bundle=CandidateBundle.model_validate({**body,'checksum':checksum(body)})
    async def model_answer(self,instruction,context,output,**kwargs):
        decisions=[]
        for group in context['groups']:
            entity=group['context']['kind']=='entity'
            relation=group['context']['kind']=='relation'
            decisions.append({'group_id':group['group_id'],'action':'new','reason':'Synthetic source-backed test',
                'new_concept':{'code':'memory_part_of_server' if relation else 'cpu_target' if entity else 'frequency',
                    'name':'Memory part of Server' if relation else 'CPU target' if entity else 'Frequency',
                    'description':'Physical specification target containment' if relation else 'CPU specification target' if entity else 'Frequency requirement of Memory',
                    'value_type':None if entity or relation else 'decimal','unit':None if entity or relation else 'GHz'},
                'units':[] if entity or relation else [{'source_unit':'GHz','canonical_unit':'GHz'}],
                'citations':[{'observation_index':0,'quote':'Server contains RAM' if relation else 'CPU' if entity else '3GHz'}]})
        return {'decisions':decisions}
    monkeypatch.setattr('teoria_codex_inference.CodexRunner.generate',model_answer)
    result=await run_semantic_cycle(profiles,rid,[bundle],model='synthetic_model',version='2',actor='test:authenticated_principal',auto_approve=True)
    assert result['status']=='approved' and result['auto_approved'] and result['new_concepts']==3
    exported=await profiles.export(UUID(result['profile_revision_id']))
    assert len(exported.profile.entities)==3 and len(exported.profile.requirements)==1 and len(exported.profile.relations)==1
    assert exported.approval_actor=='test:authenticated_principal'
    assert (await authoring.get_version(vid))['status']=='deprecated'
    assert (await profiles.export(rid)).profile.version=='1'
    events=await profiles.audit(UUID(result['profile_revision_id']))
    assert [e['action'] for e in events]==['created','submit','approve']
    assert all(e['actor']=='test:authenticated_principal' for e in events)
    detail=await authoring.get_version(exported.profile.ontology.version_id)
    assert detail['relationships'][0]['description']=='Physical specification target containment'
    cloned=await authoring.create_draft(namespace,version='3',actor='test:owner')
    detail=await authoring.get_version(UUID(cloned['ontology_version_id']))
    assert detail['relationships'][0]['description']=='Physical specification target containment'
