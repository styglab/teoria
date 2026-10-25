"""Domain opt-in and source fidelity across server and non-server observations."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from teoria_pipelines.domains.public_procurement.specification_processing.models import StandardArtifact,ContextBinding,PropertyBinding
from teoria_pipelines.domains.public_procurement.specification_processing.standardization import server_rules
from teoria_pipelines.domains.public_procurement.specification_processing.standardization.candidate_collection import target_type
from teoria_pipelines.domains.public_procurement.specification_processing.standardization.standard_application import map_standard
from teoria_pipelines.domains.public_procurement.specification_processing.standardization.standard_versioning import manage_standard
from teoria_pipelines.domains.public_procurement.specification_processing.extraction.attribute_validation import is_spec


def corpus(name='압력 펌프',key='operating_pressure',value='40',unit='MPa',classification='4110000000'):
    text=f'{name} {value}{unit or ""} 이상 개별 장치당'
    return {'classification_code':classification,'documents':[{
        'document_id':'doc','entities':[{'id':'target','name':name,'kind':'equipment'}],
        'relations':[],'parsed_document':{'nodes':[{'node_id':'n','kind':'cell','text':text}]},
        'attributes':[{'id':'a','subject_ids':['target'],'property_key':key,'property_raw':None,
            'value_raw':value,'unit_raw':unit,'data_type':'number','operator':'gte','operator_raw':'이상',
            'qualifiers_raw':['개별 장치당'],'semantic_role':'requirement_candidate','semantic_scope':'per_component',
            'evidence':{'node_id':'n'}}]}],'unavailable_documents':[]}


def standard_for(data,rule_set='source_only',kind='source_literal',target=None):
    name=data['documents'][0]['entities'][0]['name']
    a=data['documents'][0]['attributes'][0]
    return StandardArtifact(version='test_v1',classification_code=data['classification_code'],rule_set=rule_set,
        definitions=[{'id':'pressure_requirement','label':'원문 압력 요구'}],
        bindings=[ContextBinding(target_types=[target or f'equipment:{name}'],property_key=a['property_key'],
            unit_context=a['unit_raw'],data_type=a['data_type'],role=a['semantic_role'],semantic_scope=a['semantic_scope'],
            properties=[PropertyBinding(property_id='pressure_requirement',rule_kind=kind)])])


def test_unknown_non_server_meaning_survives_without_server_rules(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('server-specific rule was invoked')
    for name in ('entity_type','normalized_value','select_typed_definition','select_source_constraint'):
        monkeypatch.setattr(server_rules,name,forbidden)
    data=corpus();before=deepcopy(data)
    draft,candidates,result=manage_standard(data)
    assert draft.rule_set=='source_only' and not draft.definitions
    assert candidates['summary']['observations']==1
    candidate=candidates['candidates'][0]
    assert candidate['concept_key']=='operating_pressure'
    assert candidate['target_type_candidate']=='equipment:압력 펌프'
    assert candidate['automatic_resolution']['reasons']=={'unresolved_meaning_preserved_as_candidate':1}
    assert result['attributes'][0]['status']=='automatically_deferred'
    assert data==before


def test_server_classification_alone_does_not_enable_server_aliases():
    data=corpus('Memory','memory_frequency','5600','MHz','4321150102')
    draft,candidates,result=manage_standard(data)
    assert draft.rule_set=='source_only'
    assert candidates['candidates'][0]['concept_key']=='memory_frequency'
    assert candidates['candidates'][0]['target_type_candidate']=='equipment:Memory'
    assert result['summary']=={'automatically_deferred':1}


def test_generic_standard_applies_raw_condition_without_server_inference(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('server classifier was invoked')
    monkeypatch.setattr(server_rules,'entity_type',forbidden)
    data=corpus();result=map_standard(data,standard_for(data))
    fact=result['attributes'][0]['facts'][0]
    assert fact['subject_ids']==['target'] and fact['operator']=='gte'
    assert fact['operator_raw']=='이상' and fact['qualifiers_raw']==['개별 장치당']
    assert fact['value']=={'kind':'source_constraint','text':'40','unit_raw':'MPa',
        'resolution':'source_preserved','numeric_ordering_allowed':False}


@pytest.mark.parametrize('field,value',[('unit_raw','GB'),('operator_raw','이하'),('qualifiers_raw',['시스템 전체'])])
def test_generic_mapping_rejects_unsupported_literal_conditions(field,value):
    data=corpus();standard=standard_for(data)
    data['documents'][0]['attributes'][0][field]=value
    # Unit mismatch may fail the binding first, but must never create a fact.
    row=map_standard(data,standard)['attributes'][0]
    assert row['status']=='automatically_deferred' and 'facts' not in row


def test_binding_cannot_transfer_per_component_requirement_to_system_total():
    data=corpus();standard=standard_for(data)
    data['documents'][0]['attributes'][0]['semantic_scope']='system_total'
    assert map_standard(data,standard)['summary']=={'automatically_deferred':1}


def test_server_literal_binding_requires_explicit_server_standard():
    data=corpus(classification='4321150102')
    with pytest.raises(ValidationError,match='explicitly selected server'):
        standard_for(data,kind='server_literal')


def test_server_rule_set_cannot_be_used_for_another_classification():
    with pytest.raises(ValidationError,match='computer-server classification'):
        StandardArtifact(version='test',classification_code='4110000000',rule_set='server',definitions=[],bindings=[])


def test_explicit_server_rules_still_select_known_meaning_and_survive_versioning():
    data=corpus('CPU','thermal_design_power','150','W','4321150102')
    baseline=StandardArtifact(version='server_v1',classification_code='4321150102',rule_set='server',definitions=[],bindings=[])
    draft,candidates,result=manage_standard(data,baseline,parent_sha256='a'*64)
    assert draft.rule_set=='server' and draft.parent_standard_sha256=='a'*64
    assert candidates['candidates'][0]['concept_key']=='cpu_thermal_design_power'
    assert result['summary']=={'applied':1}
    fact=result['attributes'][0]['facts'][0]
    assert fact['property_id']=='cpu_thermal_design_power' and fact['value']['unit']=='W'
    assert map_standard(data,draft)==result


def test_source_target_labels_do_not_turn_gas_ports_into_network_components():
    assert target_type({'name':'가스 공급 포트','kind':'equipment'})=='equipment:가스 공급 포트'
    assert target_type({'name':'CPU','kind':'unknown'})=='unresolved'


@pytest.mark.parametrize('text',['압력 40MPa','유량 10mL/min','온도 120℃','진동 5mm/s','재질은 내식성이어야 하며 설치 필수'])
def test_recovery_signals_cover_non_server_specifications(text):
    assert is_spec(text)
