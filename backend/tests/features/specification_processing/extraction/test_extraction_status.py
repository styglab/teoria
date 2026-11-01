import pytest

from teoria.features.specification_processing.extraction.extraction_status import document_extraction_status


@pytest.mark.parametrize('kind', ['sends_data_to','compatible_with','depends_on','supports','service_for','document_for'])
def test_supplementary_hold_never_hides_attribute_or_document_failures(kind):
    graph={'held_relations':[{'kind':kind}]}
    assert document_extraction_status({'status':'partial'},graph,{})=='partial'
    assert document_extraction_status({'status':'needs_review'},graph,
                                      {'document_assessment':{'status':'needs_review'}})=='partial'


@pytest.mark.parametrize('kind', ['component_of','physical_part_of','ingredient_of','material_of',
                                  'packaging_for','pack_unit_of','specification_for','same_target_as','unknown'])
def test_composition_identity_or_unknown_relationships_remain_blocking(kind):
    assert document_extraction_status({'status':'needs_review'},{'held_relations':[{'kind':kind}]},{})=='partial'


def test_unreadable_ocr_page_keeps_document_partial_even_when_other_pages_succeeded():
    from teoria.features.specification_processing.extraction.extraction_status import document_extraction_status
    assert document_extraction_status({'status':'needs_review'}, {'held_relations':[]},
        {'document_assessment':{'status':'classified'},'unreadable_ocr_pages':[2]})=='partial'
