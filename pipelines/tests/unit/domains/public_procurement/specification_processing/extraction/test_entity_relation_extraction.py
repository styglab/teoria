import unittest
from pathlib import Path
from teoria_pipelines.domains.public_procurement.specification_processing.extraction.entity_relation_extraction import Inventory,Details,validate_inventory,validate_details,project_root_identifier,materialize

class FrozenInventoryChecks(unittest.TestCase):
    def fixture(self):
        values={'nr':'서버 시스템 1 set','nb':'장비의 구성','na':'CPU','nq':'2 개','nc':'RAM','nf':'팬','ns':'16코어 이상'}
        document={'document_id':'test','nodes':[{'node_id':id,'text':text,'native_ref':'/'+id,'kind':'paragraph'} for id,text in values.items()]}
        inventory=Inventory(root=('nr','서버 시스템','1','set',['nr']),basis='configuration_list',basis_node_ids=['nb'],
                            items=[('i1','na','CPU','2','개',['na','nq']),('i2','nc','RAM',None,None,['nc'])],integrated_scope=True,scope_evidence_node_ids=['nr'],issues=[])
        details=Details(additional=[('a1','nf','팬')],types=[('root','equipment','required'),('i1','equipment','required'),('i2','equipment','required'),('a1','equipment','required')],
                        relations=[('a1','i1','component_of','explicit',['nf'])],scopes=[('i1',['ns'])],issues=[])
        return document,inventory,details

    def test_inventory_item_names_and_quantities_are_source_grounded(self):
        doc,inv,detail=self.fixture();self.assertEqual(validate_inventory(inv,doc),[])
        inv.items[0]=('i1','na','CPU','99','개',['na','nq'])
        self.assertTrue(any('quantity' in e for e in validate_inventory(inv,doc)))

    def test_detailed_section_cannot_recreate_a_frozen_item(self):
        doc,inv,detail=self.fixture();detail.additional.append(('a2','na','CPU'));detail.types.append(('a2','equipment','required'))
        self.assertTrue(any('recreated frozen' in e for e in validate_details(detail,inv,doc)))

    def test_root_node_alias_projection_changes_ids_only(self):
        doc,inv,detail=self.fixture();detail.types[0]=('nr','equipment','required');detail.scopes.append(('nr',['nb']))
        projected,alias=project_root_identifier(detail,inv)
        self.assertEqual(alias,{'nr':'root'});self.assertEqual(projected.types[0][0],'root')
        self.assertEqual(detail.types[0][0],'nr');self.assertEqual(projected.additional,detail.additional)
        self.assertEqual(validate_details(projected,inv,doc),[])

    def test_ambiguous_root_alias_is_not_silently_collapsed(self):
        doc,inv,detail=self.fixture();detail.additional.append(('nr','nr','서버 시스템'));detail.types.append(('nr','equipment','required'))
        projected,alias=project_root_identifier(detail,inv);self.assertEqual(alias,{})

    def test_quantities_stay_on_the_explicit_inventory_target(self):
        doc,inv,detail=self.fixture();graph=materialize(inv,detail,doc)
        self.assertEqual(graph['inventory_ids'],['i1','i2'])
        quantities={q['entity_id']:q['value_raw'] for q in graph['declared_quantities']}
        self.assertEqual(quantities,{'root':'1','i1':'2'})
        self.assertNotIn('a1',quantities)

    def test_inventory_cells_still_become_source_clauses(self):
        doc,inv,detail=self.fixture();graph=materialize(inv,detail,doc)
        clauses={e['node_id'] for q in graph['requirements'] if q['observation_type']=='source_clause' for e in q['evidence']}
        self.assertTrue({'na','nq','nc','nb'}<=clauses)

    def test_fallback_section_groups_are_labeled_as_document_scopes(self):
        doc,inv,detail=self.fixture();inv.basis='technical_sections'
        graph=materialize(inv,detail,doc)
        self.assertTrue(all(e.get('basis_role')=='document_scope' for e in graph['entities'] if e['id'] in ['i1','i2']))
        self.assertTrue(all('supply_target' not in e['document_roles'] for e in graph['entities'] if e['id'] in ['i1','i2']))

