"""Synthetic memory capacity: document requirement and API value share published meaning."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
import hashlib
import shutil

import pytest
import yaml

from backend.tests.integration.test_goods_normalization_contract import example, uid
from teoria.domains.goods.normalization.comparison import compare_property_observations
from teoria.domains.goods.normalization.contracts import checksum
from teoria.domains.goods.normalization.profiles.compiler import compile_package
from teoria.domains.goods.normalization.application.profile_application import apply_profile
from teoria.platform.ontology.contracts.loader import RegistryLoader
from teoria.platform.ontology.contracts.mapping_semantics import compile_mapping_semantics
from teoria.platform.ontology.contracts.schema.mapping import MappingDefinition
from teoria.platform.ontology.contracts.schema.common import FieldDefinition
from teoria.platform.ontology.contracts.schema.runtime_contract import RuntimeContractProperty
from teoria.platform.ontology.contracts.artifact import RuntimeBundleCompiler, RuntimeBundleLoader, RegistryArtifactError
from teoria.platform.ontology.contracts.release import publish_registry
from teoria.platform.ontology.runtime.mapping.decoder import MappingDecoder
from teoria.platform.ontology.runtime.mapping.materializer import OntologyMaterializer
from teoria.platform.ontology.runtime.capability.contracts import CapabilityResult
from teoria.platform.ontology.runtime.capability.presentation import serialize_capability_result
from teoria.integrations.provider_api.models import ExecutionResponse


def memory_case():
    catalog = RegistryLoader(Path('backend/tests/fixtures/registry')).load()
    profile, ontology, corpus = example()
    for obj in ontology['objects']:
        obj.update(name=obj['stable_key'], description='Synthetic memory meaning')
        for prop in obj['properties']:
            prop.update(name=prop['stable_key'], description='Synthetic property meaning')
    capacity = ontology['objects'][0]['properties'][0]
    capacity.update(quantity_dimension='information', allowed_units=['GB','TB'])
    profile = profile.model_copy(update={'ontology':profile.ontology.model_copy(update={'checksum':checksum(ontology)})})
    source = catalog.sources['example_api'].source
    record = next(o for o in source.components.objects if o.id == 'record')
    record.fields.extend([FieldDefinition(id='capacity_tb',data_type='number',name='Synthetic manufacturer capacity in decimal TB'),
                          FieldDefinition(id='effective_at',data_type='datetime')])
    runtime = next(o for o in catalog.runtime_contracts['example'].object_types if o.id == 'record')
    runtime.properties.append(RuntimeContractProperty(id='capacity_gb',name='Capacity',description='Synthetic declared capacity',data_type='number'))
    binding = {'binding_id':uid(700), 'status':'approved','approved_by':'fixture:reviewer','binding_type':'represents',
               'ontology_concept_id':uid(2), 'ontology_namespace':'goods_test','ontology_stable_key':'goods_test.memory.capacity',
               'target_type':'api_field','api_source_id':'example_api','api_operation_id':'get_records',
               'api_object_id':'record','api_field_path':'capacity_tb','api_contract_version':'1.0.0'}
    meaning = {'ontology':profile.ontology.model_dump(mode='json'),'concept_id':uid(2),
               'api_field_binding_id':binding['binding_id'],'information_kind':'declared_value','scope':'per_component',
               'unit':{'source_unit':'TB','canonical_unit':'GB','multiplier':'1000'},'effective_at_field':'effective_at'}
    mapping = MappingDefinition(id='memory_capacity',description='Synthetic API field to memory property',ontology='example',
        bindings={'record.record_id':[{'field':'example_api.get_records.response.code'}],
                  'record.capacity_gb':[{'field':'example_api.get_records.response.capacity_tb','meaning':meaning}]},
        materializations={'example_api.get_records':{'objects':{'record':{'type':'record','identity':['record_id']}}}})
    catalog.mappings[mapping.id] = mapping
    catalog.mapping_paths[mapping.id] = Path('domains/example/mappings/memory_capacity.yaml')
    artifact = {'ontology_version_id':str(profile.ontology.version_id),'namespace':ontology['namespace'],
                'version':ontology['version'],'checksum':checksum(ontology),'content':ontology}
    return catalog, profile, ontology, corpus, [artifact], [binding]


def api_value(catalog, capacity=0.064, *, observed_at=datetime(2026,11,8,tzinfo=timezone.utc)):
    response = ExecutionResponse(status_code=200,content_type='application/json',headers={},elapsed_ms=1,
        body={'status_code':'OK','data':[{'code':'MEMORY_MODEL_64','capacity_tb':capacity,'effective_at':'2026-11-01T00:00:00Z'}]})
    fragments = MappingDecoder().decode(catalog,'example_api','get_records',response,observed_at=observed_at)
    objects, _ = OntologyMaterializer().materialize(catalog,fragments,datetime(2026,11,8,tzinfo=timezone.utc),{'example.record'},set())
    return objects[0]


def test_api_binding_validity_is_checked_when_the_record_is_read():
    from datetime import date
    catalog, _, _, _, artifacts, bindings = memory_case()
    bindings[0]['valid_to']='2026-11-09'
    catalog.mapping_semantics=compile_mapping_semantics(catalog,artifacts,bindings,on_date=date(2026,11,8))
    assert api_value(catalog).semantic_observations
    with pytest.raises(ValueError,match='mapping_binding_outside_validity'):
        api_value(catalog,observed_at=datetime(2026,11,10,tzinfo=timezone.utc))


def document_requirement(profile, ontology, corpus):
    package = compile_package(profile,ontology,revision_id=UUID(int=900),approval_actor='fixture:reviewer')
    doc = corpus['documents'][0]
    reference = profile.ontology.model_dump(mode='json')
    alignment = {'policy_version':'published_ontology_expression_v2','documents':[{
        'document_id':doc['document_id'],
        'entities':[{'id':e['id'],'meaning_status':'resolved','ontology':reference,'ontology_concept_ref':uid(4) if e['id']=='root' else uid(1)} for e in doc['entities']],
        'attributes':[{'id':a['id'],'meaning_status':'resolved','ontology':reference,'ontology_concept_ref':uid(3) if a['property_key']=='quantity' else uid(2)} for a in doc['attributes']]}]}
    normalized, _ = apply_profile(corpus,package,run_id='memory_bridge',meaning_alignment=alignment)
    return normalized['documents'][0]['requirements'][0]['semantic_observation']


def test_memory_document_and_api_share_meaning_units_and_traceable_observations():
    catalog, profile, ontology, corpus, artifacts, bindings = memory_case()
    catalog.mapping_semantics = compile_mapping_semantics(catalog,artifacts,bindings)
    original = deepcopy(corpus)
    requirement = document_requirement(profile,ontology,corpus)
    obj = api_value(catalog)
    declared = obj.semantic_observations[0].model_dump(mode='json')
    assert corpus == original
    assert requirement['concept_id'] == declared['concept_id'] == uid(2)
    assert requirement['ontology'] == declared['ontology']
    assert requirement['information_kind']=='requirement' and declared['information_kind']=='declared_value'
    assert requirement['operator']=='gte' and declared['operator']=='eq'
    assert requirement['value']['decimal']=='64' and declared['value']['decimal']=='64.000'
    assert declared['unit_raw']=='TB' and declared['value_raw']==0.064
    assert declared['source']['field_path']=='capacity_tb' and declared['source']['api_field_binding_id']==uid(700)
    assert declared['effective_at']=='2026-11-01T00:00:00Z'
    assert compare_property_observations(requirement,declared)['reason']=='reviewed_subject_link_required'
    links={(requirement['subject_refs'][0],obj.object_id)}
    assert compare_property_observations(requirement,declared,subject_links=links)['status']=='satisfied'
    smaller=api_value(catalog,0.032).semantic_observations[0]
    assert compare_property_observations(requirement,smaller,subject_links=links)['status']=='not_satisfied'
    output=serialize_capability_result(CapabilityResult(capability_id='synthetic_only',objects=[obj]))
    assert output['objects'][0]['semantic_observations'][0]['source']['kind']=='api'


async def test_disabling_expression_registration_does_not_bypass_approved_meaning_links(tmp_path):
    import json
    from teoria.domains.goods.contracts import SpecificationRun
    from teoria.domains.goods.workflows.tasks import select_and_map_standard
    _, profile, ontology, corpus, _, _ = memory_case()
    original = deepcopy(corpus)
    package = compile_package(profile, ontology, revision_id=UUID(int=900), approval_actor='fixture:reviewer')
    raw = package.model_dump_json().encode()
    path = tmp_path / 'package.json'
    path.write_bytes(raw)
    (tmp_path / 'extracted.json').write_text(json.dumps(corpus))
    request = SpecificationRun(run_id='without_dictionary', mode='document_processing',
        classification_code=corpus['classification_code'], use_expression_dictionary=False,
        artifact_root=(tmp_path / 'artifacts').as_uri(),
        documents=[{'document_id':'input', 'filename':'input.pdf', 'source_uri':'file:///input.pdf'}],
        standard={'uri':path.as_uri(), 'sha256':hashlib.sha256(raw).hexdigest()})
    await select_and_map_standard.fn(request, str(tmp_path), dictionary=None)
    normalized = json.loads((tmp_path / 'normalized.json').read_text())
    assert normalized['summary'].get('applied', 0) == 0
    assert all(not document['requirements'] for document in normalized['documents'])
    assert any(c['reason'] == 'unresolved_ontology_mapping' for c in normalized['unresolved_observations'])
    assert json.loads((tmp_path / 'extracted.json').read_text()) == original


@pytest.mark.parametrize('change,code',[
    ('draft_binding','mapping_approved_api_binding_required'),
    ('wrong_field','mapping_api_binding_target_mismatch'),
    ('old_source_version','mapping_api_binding_target_mismatch'),
    ('missing_ontology','mapping_ontology_publication_missing'),
    ('wrong_type','mapping_runtime_property_type_mismatch'),
    ('conditional','mapping_conditional_binding_requires_review'),
    ('related','mapping_binding_is_not_equivalence'),
    ('unit','published property unit policy'),
    ('wrong_owner','mapping_materialized_owner_mismatch'),
    ('codec','mapping_governed_codec_requires_review'),
])
def test_mapping_requires_reviewed_exact_field_publication_type_and_unit(change, code):
    catalog, _, _, _, artifacts, bindings = memory_case()
    if change=='draft_binding':bindings[0]['status']='draft'
    elif change=='wrong_field':bindings[0]['api_field_path']='status'
    elif change=='old_source_version':bindings[0]['api_contract_version']='old'
    elif change=='missing_ontology':artifacts=[]
    elif change=='wrong_type':catalog.runtime_contracts['example'].object_types[0].properties[-1].data_type='string'
    elif change=='conditional':bindings[0]['condition']={'some_context':True}
    elif change=='related':bindings[0]['binding_type']='related'
    elif change=='wrong_owner':catalog.mappings['memory_capacity'].materializations['example_api.get_records'].objects['record'].type='group'
    elif change=='codec':catalog.mappings['memory_capacity'].bindings['record.capacity_gb'][0].decode='common.parse_date'
    elif change=='unit':
        artifacts[0]['content']['objects'][0]['properties'][0]['allowed_units']=['GB']
        digest=checksum(artifacts[0]['content']);artifacts[0]['checksum']=digest
        catalog.mappings['memory_capacity'].bindings['record.capacity_gb'][0].meaning.ontology.checksum=digest
    with pytest.raises(ValueError,match=code):compile_mapping_semantics(catalog,artifacts,bindings)


def test_unverified_mapping_and_untyped_values_cannot_execute():
    catalog, _, _, _, artifacts, bindings = memory_case()
    with pytest.raises(ValueError,match='verified_mapping_semantics_required'):api_value(catalog)
    catalog.mapping_semantics=compile_mapping_semantics(catalog,artifacts,bindings)
    for bad in [True, float('nan'), 'not_a_number', '0.064']:
        with pytest.raises(ValueError,match='invalid_number|mapping_source_number_type_mismatch'):api_value(catalog,bad)


def test_different_values_are_preserved_and_the_flat_projection_is_held_for_review():
    catalog, _, _, _, artifacts, bindings = memory_case()
    catalog.mapping_semantics=compile_mapping_semantics(catalog,artifacts,bindings)
    response=ExecutionResponse(status_code=200,content_type='application/json',headers={},elapsed_ms=1,
        body={'data':[{'code':'SAME_MODEL','capacity_tb':n,'effective_at':'2026-11-01T00:00:00Z'} for n in [0.064,0.032]]})
    fragments=MappingDecoder().decode(catalog,'example_api','get_records',response)
    objects,_=OntologyMaterializer().materialize(catalog,fragments,datetime(2026,11,8,tzinfo=timezone.utc),{'example.record'},set())
    assert len(objects)==1
    obj=objects[0]
    assert len(obj.semantic_observations)==2
    assert {o.value_raw for o in obj.semantic_observations}=={0.064,0.032}
    assert 'capacity_gb' not in obj.properties
    assert obj.semantic_conflicts=={'capacity_gb':'multiple_observations_require_review'}


def test_one_runtime_property_cannot_mix_measurement_and_declared_value():
    catalog, _, _, _, artifacts, bindings = memory_case()
    rule=catalog.mappings['memory_capacity'].bindings['record.capacity_gb'][0]
    measurement=rule.model_copy(deep=True)
    measurement.meaning.information_kind='measurement'
    catalog.mappings['memory_capacity'].bindings['record.capacity_gb'].append(measurement)
    with pytest.raises(ValueError,match='mapping_property_mixes_observation_contexts'):
        compile_mapping_semantics(catalog,artifacts,bindings)


def test_comparison_does_not_turn_measurements_limits_or_unreviewed_conditions_into_product_facts():
    catalog, profile, ontology, corpus, artifacts, bindings=memory_case()
    catalog.mapping_semantics=compile_mapping_semantics(catalog,artifacts,bindings)
    requirement=document_requirement(profile,ontology,corpus)
    obj=api_value(catalog)
    candidate=obj.semantic_observations[0].model_dump(mode='json')
    links={(requirement['subject_refs'][0],obj.object_id)}
    for changed,reason in [
        ({'information_kind':'capability'},'incompatible_information_kind'),
        ({'scope':'system_total'},'different_scope'),
        ({'conditions':['under test conditions']},'condition_review_required'),
        ({'information_kind':'measurement','effective_at':None},'measurement_time_required'),
        ({'ontology':{**candidate['ontology'],'version':'other'}},'different_published_concept')]:
        assert compare_property_observations(requirement,{**candidate,**changed},subject_links=links)['reason']==reason


def test_runtime_bundle_revalidates_mapping_and_frozen_publication_survives_new_authoring(tmp_path):
    catalog, _, _, _, artifacts, bindings = memory_case()
    root=tmp_path/'registry'
    shutil.copytree('backend/tests/fixtures/registry',root)
    # This fixture exercises mapping only; do not activate unrelated example capabilities.
    for path in root.rglob('*.yaml'):
        if path.parent.name == 'capabilities':
            path.unlink()
    source=catalog.sources['example_api']
    (root/'sources/example_api.yaml').write_text(yaml.safe_dump(source.model_dump(mode='json',by_alias=True),allow_unicode=True))
    runtime_path=catalog.runtime_contract_paths['example'].relative_to(catalog.root)
    (root/runtime_path).write_text(yaml.safe_dump({'registry':{'version':'1.0.0','registered_at':'2026-11-08'},
        'runtime_contract':catalog.runtime_contracts['example'].model_dump(mode='json')},allow_unicode=True))
    mapping_path=root/'domains/example/mappings/memory_capacity.yaml'
    mapping_path.write_text(yaml.safe_dump({'registry':{'version':'1.0.0','registered_at':'2026-11-08'},
        'mapping':catalog.mappings['memory_capacity'].model_dump(mode='json')},allow_unicode=True))
    publish_registry(root,version='2026.11.08.1',output=tmp_path/'registry_artifacts',git_commit='synthetic_fixture')
    compiler=RuntimeBundleCompiler()
    compiler.compile(tmp_path/'registry_artifacts/2026.11.08.1',ontologies=artifacts,bindings=bindings,
        output=tmp_path/'bundles',created_at=datetime(2026,11,8,tzinfo=timezone.utc))
    bundle=RuntimeBundleLoader(tmp_path/'bundles/2026.11.08.1').load()
    assert api_value(bundle.catalog).semantic_observations[0].value['unit']=='GB'
    artifacts[0]['content']['objects'][0]['properties'][0]['unit']='TB'
    artifacts[0]['checksum']=checksum(artifacts[0]['content'])
    with pytest.raises(RegistryArtifactError,match='Mapping semantics'):
        compiler.compile(tmp_path/'registry_artifacts/2026.11.08.1',ontologies=artifacts,bindings=bindings,
            output=tmp_path/'new_bundles',version='2026.11.08.2')
    assert api_value(bundle.catalog).semantic_observations[0].value['unit']=='GB'
