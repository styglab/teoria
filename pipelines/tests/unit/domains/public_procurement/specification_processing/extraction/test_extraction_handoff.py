"""Regression cases for source-cell loss, bounded recovery and configuration attribution."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from teoria_pipelines.domains.public_procurement.specification_processing.extraction.attribute_chunking import make_chunks
from teoria_pipelines.domains.public_procurement.specification_processing.extraction.attribute_validation import deduplicate_inventory,fragment_context
from teoria_pipelines.domains.public_procurement.specification_processing.extraction.attribute_resolution import resolve_attribute_semantics

class HandoffChecks(unittest.TestCase):
 def test_inventory_cell_is_forwarded_even_with_an_old_graph(self):
  doc={'nodes':[{'node_id':'list','kind':'cell','text':'CPU Xeon 6515P 16-Core\nMemory 16GB DDR5'}, {'node_id':'title','kind':'paragraph','text':'규격서'}]}
  graph={'requirements':[{'observation_type':'inventory_quantity','subject_ids':['cpu'],'evidence':[{'node_id':'list'}]}]}
  fragments=[f for c in make_chunks(graph,doc) for f in c]
  self.assertEqual({f['node_id'] for f in fragments},{'list','title'})
  self.assertEqual(''.join(f['text'] for f in fragments if f['node_id']=='list'),doc['nodes'][0]['text'])
 def test_row_label_and_column_header_are_attached_as_context(self):
  doc={'nodes':[{'node_id':'header','text':'상세 규격','source_table_id':'t','row':0,'column':1},
       {'node_id':'body','text':'본체','source_table_id':'t','row':1,'column':0},
       {'node_id':'spec','text':'Up to 6400MHz','source_table_id':'t','row':1,'column':1}]}
  context=fragment_context(doc,{'node_id':'spec'})
  self.assertEqual({c[0] for c in context},{'header','body'})
 def test_only_exact_inventory_quantity_duplicate_is_removed(self):
  q={'id':'q','subject_ids':['cpu'],'value_raw':'2','unit_raw':'개','evidence':{'source_node_ids':['n']}}
  a={'id':'a','property_key':'quantity','subject_ids':['cpu'],'value_raw':'2','unit_raw':'개','operator':'eq','qualifiers_raw':[],'evidence':{'node_id':'n'}}
  kept,duplicates=deduplicate_inventory([q],[a])
  self.assertEqual(kept,[]);self.assertEqual(duplicates[0]['duplicate_of'],'q')
  a['qualifiers_raw']=['추가 지원']
  self.assertEqual(deduplicate_inventory([q],[a])[0],[a])

class SemanticChecks(unittest.IsolatedAsyncioTestCase):
 async def test_support_limit_moves_to_body_without_changing_the_source_value(self):
  doc={'nodes':[{'node_id':'spec','kind':'cell','text':'본체: 최대 6400MHz 지원'}]}
  graph={'entities':[{'id':'body','name':'본체','kind':'equipment'},{'id':'ram','name':'RAM','kind':'equipment'}],'relations':[]}
  a={'id':'a','subject_ids':['ram'],'property_key':'memory_frequency','value_raw':'6400','unit_raw':'MHz','operator_raw':'최대','qualifiers_raw':['지원'],'evidence':{'node_id':'spec'}}
  class Model:
   async def generate(self,prompt,request,out):
    return {'resolutions':[{'attribute_id':'a','subject_ids':['body'],'role':'supported_capability','scope':'support_limit','evidence_node_ids':['spec']}]}
  with TemporaryDirectory() as directory:
   result=await resolve_attribute_semantics(doc,graph,[a],Model(),Path(directory))
  self.assertEqual(a['subject_ids'],['body']);self.assertEqual(a['extraction_subject_ids'],['ram'])
  self.assertEqual(a['semantic_role'],'supported_capability');self.assertEqual(a['value_raw'],'6400')
  self.assertEqual(result['reassigned'],1)
 async def test_nonexistent_target_becomes_unknown_instead_of_bypassing_validation(self):
  doc={'nodes':[{'node_id':'n','kind':'paragraph','text':'CPU 16core'}]}
  graph={'entities':[{'id':'cpu','name':'CPU','kind':'equipment'}],'relations':[]}
  a={'id':'a','subject_ids':['cpu'],'evidence':{'node_id':'n'}}
  class Model:
   async def generate(self,prompt,request,out):
    return {'resolutions':[{'attribute_id':'a','subject_ids':['invented'],'role':'requirement_candidate','scope':'per_processor','evidence_node_ids':['n']}]}
  with TemporaryDirectory() as directory:result=await resolve_attribute_semantics(doc,graph,[a],Model(),Path(directory))
  self.assertEqual(a['subject_ids'],[]);self.assertEqual(a['semantic_role'],'unknown');self.assertEqual(result['unresolved'],1)
