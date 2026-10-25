import unittest
from teoria_pipelines.domains.public_procurement.specification_processing.extraction.attribute_extraction import spans,normalize_fact,decode_batch,make_chunks

class AttributeMeaningChecks(unittest.TestCase):
    def test_nfkc_unit_span_points_to_original_character(self):
        text='폭 800㎜ 이상';found=spans(text,'800 mm')
        self.assertEqual(found,[[2,6]])
        self.assertEqual(text[found[0][0]:found[0][1]],'800㎜')
    def test_partial_unicode_expansion_is_not_a_source_span(self):
        self.assertEqual(spans('⑩ 1회','1'),[[2,3]])
        self.assertEqual(spans('⑩ 1회','10'),[[0,1]])
        self.assertEqual(spans('㎜','m'),[])

    def test_model_identifiers_are_never_numerically_ordered(self):
        value=normalize_fact('processor_model','identifier','raw','Intel Core i5',None)
        self.assertIsNone(value['comparison_rule']);self.assertEqual(value['value'],'Intel Core i5')
        self.assertIsNone(normalize_fact('model','number','gte','5515',None)['comparison_rule'])
    def test_numeric_threshold_and_unit(self):
        value=normalize_fact('capacity','number','gte','8','GB')
        self.assertEqual(value['value'],'8');self.assertEqual(value['unit'],'GB');self.assertEqual(value['comparison_rule'],'numeric_requirement')
    def test_range_bounds_are_preserved(self):
        value=normalize_fact('flow_range','range','range','0.0001~10','mL/min')
        self.assertEqual(value['value'],{'min':'0.0001','max':'10'})
    def test_ambient_relative_temperature_is_not_absolute(self):
        value=normalize_fact('temperature_range','range','range','상온-10 ℃ ~ 100 ℃','℃')
        self.assertIsNone(value['comparison_rule']);self.assertIsInstance(value['value'],str)
    def test_ambiguous_storage_g_is_not_gb(self):
        value=normalize_fact('capacity','number','raw','250','G')
        self.assertEqual(value['unit_status'],'unmapped');self.assertIsNone(value['unit']);self.assertIsNone(value['comparison_rule'])
    def test_fabricated_value_is_quarantined_without_discarding_other_facts(self):
        graph={'document_id':'test','entities':[{'id':'ram','name':'RAM','kind':'equipment'}]}
        doc={'nodes':[{'node_id':'n','text':'RAM 8GB 이상','native_ref':'/blocks/1'}]}
        chunk=[{'id':'f','node_id':'n','start':0,'end':10,'text':'RAM 8GB 이상','suggested_subject_ids':['ram']}]
        valid=['f',['ram'],'capacity','RAM','number','gte','이상','8','GB',[]]
        invalid=[*valid];invalid[7]='64'
        accepted,quarantined,_=decode_batch({'facts':[valid,invalid],'unresolved':[]},chunk,graph,doc,0)
        self.assertEqual(len(accepted),1);self.assertEqual(len(quarantined),1)
        self.assertEqual(accepted[0]['normalized']['value'],'8')
    def test_long_source_fragments_keep_offsets_and_all_text(self):
        text='항목 1\n'*500
        doc={'nodes':[{'node_id':'n','text':text}]}
        graph={'requirements':[{'id':'q','subject_ids':['x'],'observation_type':'source_clause','evidence':[{'node_id':'n'}]}]}
        chunks=make_chunks(graph,doc,target_chars=100,fragment_chars=40)
        fragments=[f for c in chunks for f in c]
        self.assertEqual(''.join(f['text'] for f in fragments),text)
        self.assertTrue(all(text[f['start']:f['end']]==f['text'] for f in fragments))

if __name__=='__main__':unittest.main()

class AttributeProjectionChecks(unittest.TestCase):
    def test_missing_optional_unit_can_be_defaulted_without_semantic_edit(self):
        doc={'nodes':[{'node_id':'n','text':'모드: 고압 (2 또는 3 용매)','native_ref':'/n'}]}
        graph={'document_id':'test','entities':[{'id':'x'}]}
        chunk=[{'id':'f','node_id':'n','start':0,'end':23,'text':doc['nodes'][0]['text'],'suggested_subject_ids':['x']}]
        raw=['f',['x'],'mode','모드','text','eq',None,'고압',['2 또는 3 용매']]
        accepted,quarantined,_=decode_batch({'facts':[raw]},chunk,graph,doc,0)
        self.assertEqual(quarantined,[]);self.assertIsNone(accepted[0]['unit_raw'])
        self.assertEqual(accepted[0]['qualifiers_raw'],['2 또는 3 용매'])
        self.assertEqual(accepted[0]['wire_format_projection']['raw_prediction'],raw)

    def test_recommended_value_is_not_silently_a_mandatory_attribute(self):
        doc={'nodes':[{'node_id':'n','text':'권장 치수: 폭 800㎜ 이상','native_ref':'/n'}]}
        graph={'document_id':'test','entities':[{'id':'x'}]}
        chunk=[{'id':'f','node_id':'n','start':0,'end':20,'text':doc['nodes'][0]['text'],'suggested_subject_ids':['x']}]
        raw=['f',['x'],'width','폭','number','gte','이상','800','㎜',['권장 치수']]
        accepted,quarantined,_=decode_batch({'facts':[raw]},chunk,graph,doc,0)
        self.assertEqual(quarantined,[]);self.assertEqual(accepted[0]['modality'],'recommended')
