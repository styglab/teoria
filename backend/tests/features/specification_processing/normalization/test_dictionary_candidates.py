"""Source-expression registration must not manufacture labels from extraction keys."""
from copy import deepcopy

from teoria.features.specification_processing.normalization.dictionary_candidates import submission_from_corpus


def corpus(property_raw):
    # Vehicle original: /blocks/39/table/cells/3/1; source-backed silver excerpt.
    text='- 차량에는 대형동물의 구조·이송 및 응급처치와 간이수술이 가능한 이동형 진료대 설치·비치\n허용하중: 200kg 이상'
    return {'documents':[{
        'document_id':'vehicle','source':{'sha256':'40c6d6203877a0bdc50b8cbb4f2f71f3efcd5eb5a1c06bc9ac5756ac3c86289d'},
        'parser':{'version':'fixture'},'parsed_document':{'nodes':[
            {'node_id':'short','native_ref':'/short','text':'이동형 진료대'},
            {'node_id':'detail','native_ref':'/blocks/39/table/cells/3/1','text':text}]},
        'entities':[{'id':'table','name':'이동형 진료대','kind':'equipment','evidence':[{'node_id':'detail'}]}],
        'attributes':[{'id':'load','subject_ids':['table'],'property_key':'load_capacity','property_raw':property_raw,
            'data_type':'number','value_raw':'200','unit_raw':'kg','operator':'gte',
            'semantic_role':'requirement_candidate','semantic_scope':'per_component','evidence':{'node_id':'detail'}}],
    }]}


def test_missing_source_property_name_does_not_register_a_generated_english_key():
    original=corpus(None);before=deepcopy(original)
    submission=submission_from_corpus(original)
    assert [c.kind for c in submission.candidates]==['item_type']
    assert original==before  # The observation remains available for later semantic authoring.


def test_named_property_keeps_its_actual_owner_and_evidence():
    submission=submission_from_corpus(corpus('허용하중'))
    item,attribute=submission.candidates
    assert attribute.preferred_name=='허용하중' and attribute.owner_candidate_key==item.candidate_key
    assert attribute.evidence[0].locator=='/blocks/39/table/cells/3/1'
    assert item.evidence[0].locator=='/blocks/39/table/cells/3/1'
