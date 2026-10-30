"""Source excerpts: food purchase rows are neither equipment nor a mechanical BOM."""
import pytest

from teoria.features.specification_processing.extraction.entity_relation_extraction import (
    Details, Inventory, materialize, review_relations,
    validate_details, validate_inventory,
)


def milk_case():
    # Existing school food list: r26bk01766042_000_02/original.xlsx, sheet1 item numbers 101/102.
    texts = {
        'title': '학교급식 물품 현품설명서(일반부식)',
        'large': '우유/대(大)',
        'large_spec': '1000ml/L/국산/대(大)/식품표시기준:내용준수/유통기한/품질유지기한 표시||제조년월일 표시/국산원유100%,종이팩,HACCP인증,위생포장,표시규격품',
        'large_quantity': '3', 'large_unit': 'L',
        'small': '우유/소(小)',
        'small_spec': '500ml/EA(개)/소(小)/식품표시기준:내용준수/원유100% 국산1A등급',
        'small_quantity': '1', 'small_unit': 'EA(개)',
    }
    document = {'document_id': 'milk', 'nodes': [
        {'node_id': key, 'text': text, 'native_ref': '/' + key, 'kind': 'paragraph',
         'parent_id': None, 'row': None, 'column': None, 'row_span': None, 'column_span': None}
        for key, text in texts.items()]}
    inv = Inventory(root=('title', texts['title'], None, None, ['title']),
        basis='supply_list', basis_node_ids=['title'], integrated_scope=False,
        scope_evidence_node_ids=[], items=[
            ('large', 'large', texts['large'], '3', 'L', ['large', 'large_quantity', 'large_unit']),
            ('small', 'small', texts['small'], '1', 'EA(개)', ['small', 'small_quantity', 'small_unit']),
        ], issues=[])
    details = Details(additional=[
        ('milk_material', 'large_spec', '원유'), ('pack', 'large_spec', '종이팩')],
        types=[('root', 'group', 'required'), ('large', 'product', 'required'),
               ('small', 'product', 'required'), ('milk_material', 'material', 'required'),
               ('pack', 'product', 'required')],
        relations=[('milk_material', 'large', 'ingredient_of', 'explicit', ['large_spec']),
                   ('pack', 'large', 'packaging_for', 'explicit', ['large_spec'])],
        scopes=[('large', ['large_spec']), ('small', ['small_spec'])], issues=[])
    return document, inv, details


def test_food_rows_keep_purchase_quantities_ingredients_and_packaging_separate():
    doc, inventory, details = milk_case()
    assert validate_inventory(inventory, doc) == []
    assert validate_details(details, inventory, doc) == []
    graph = materialize(inventory, details, doc)
    assert {r['kind'] for r in graph['relations']} == {
        'in_procurement_scope', 'ingredient_of', 'packaging_for'}
    assert {q['entity_id']: (q['value_raw'], q['unit_raw']) for q in graph['declared_quantities']} == {
        'large': ('3', 'L'), 'small': ('1', 'EA(개)')}
    assert not any(e['kind'] == 'equipment' for e in graph['entities'])


@pytest.mark.parametrize('kind,source,target', [
    ('physical_part_of', 'milk_material', 'large'),
    ('installed_on', 'milk_material', 'large'),
    ('ingredient_of', 'root', 'large'),  # A document scope is not an ingredient.
])
def test_incorrect_material_and_software_roles_are_held(kind, source, target):
    doc, inventory, details = milk_case()
    details.relations = [(source, target, kind, 'explicit', ['large_spec'])]
    reviewed, held = review_relations(details, inventory, doc)
    assert not reviewed.relations and held


def test_food_and_material_expressions_remain_dictionary_candidates():
    from teoria.features.specification_processing.normalization.dictionary_candidates import submission_from_corpus
    doc, inventory, details = milk_case()
    graph = materialize(inventory, details, doc)
    corpus = {'documents': [{**graph, 'source': {'sha256': 'a' * 64},
        'parsed_document': doc, 'parser': {'version': 'fixture'}, 'attributes': []}]}
    submission = submission_from_corpus(corpus, auto_approve=False)
    assert {'우유/대(大)', '우유/소(小)', '원유'} <= {c.preferred_name for c in submission.candidates}
    assert not submission.auto_approve


async def test_contents_remain_navigation_and_cannot_establish_products_or_quantities(tmp_path):
    from teoria.features.specification_processing.extraction.entity_relation_extraction import extract_entity_relations
    from teoria.features.specification_processing.parsing.document_assessment import extraction_node_ids
    doc, inventory, details = milk_case()
    # A navigation counterexample, distinct from the real purchase rows above.
    doc['nodes'].append({'node_id': 'toc', 'text': '1. 우유 규격 .... 3',
                         'native_ref': '/toc', 'kind': 'paragraph', 'parent_id': None,
                         'row': None, 'column': None, 'row_span': None, 'column_span': None})
    doc['document_assessment'] = {'node_roles': {'toc': 'table_of_contents'}}
    assert 'toc' not in extraction_node_ids(doc, headings=True)
    class Runner:
        def __init__(self):
            self.requests = []
        async def generate(self, prompt, request, out):
            self.requests.append(request)
            return (details if 'inventory' in request else inventory).model_dump(mode='json')
    runner = Runner()
    await extract_entity_relations(doc, tmp_path, runner)
    for request in runner.requests:
        assert request['contents_nodes'] == [['toc', '1. 우유 규격 .... 3']]
        assert all(n[0] != 'toc' for n in request['nodes'])
        assert 'source_structure' in request
    bad = inventory.model_copy(update={'root': ('toc', '우유', '3', None, ['toc'])})
    assert validate_inventory(bad, doc)
    assert not any(q['id'] == 'clause_toc' for q in materialize(inventory, details, doc)['requirements'])
