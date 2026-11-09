"""Build attribute input fragments while preserving source character offsets."""
from teoria.domains.goods.data_processing.extraction.document_context import DocumentContext,pack_fragments
from teoria.domains.goods.data_processing.extraction.attribute_validation import is_spec
import re

def make_chunks(graph,document,target_chars=2200,fragment_chars=1100):
    """Split long cells at line boundaries, preserving original character offsets."""
    nodes={n['node_id']:n for n in document['nodes']};fragments=[]
    owners={}
    for clause in graph.get('requirements',[]):
        if clause.get('observation_type')!='source_clause':continue
        for evidence in clause['evidence']:
            owners.setdefault(evidence['node_id'],[]).extend(clause['subject_ids'])
    for entity in graph.get('entities',[]):
        for evidence in entity.get('evidence',[]):
            owners.setdefault(evidence['node_id'],[]).append(entity['id'])
    # Source completeness does not depend on whether an upstream graph used a cell as a label/list.
    from teoria.domains.goods.data_processing.parsing.document_assessment import extraction_node_ids
    eligible=extraction_node_ids(document,specifications_only=True)
    for node_id,node in nodes.items():
        if node_id not in eligible:continue
        text=node['text']
        if not text.strip() or node.get('kind')=='image':continue
        offset=0;start=0;size=0;parts=[]
        for line in text.splitlines(keepends=True):
            if len(text)>fragment_chars:
                # A long cell can contain many different components. Each source line keeps its own anchor.
                if size and line.strip() and text[start:offset].strip():
                    parts.append((start,offset));start=offset;size=0
                offset+=len(line);size+=len(line)
                continue
            if size and size+len(line)>fragment_chars:
                parts.append((start,offset));start=offset;size=0
            offset+=len(line);size+=len(line)
        if offset>start:parts.append((start,offset))
        for index,(a,b) in enumerate(parts):
            role=document.get('document_assessment',{}).get('node_roles',{}).get(node_id,'unknown')
            if (len(text)>fragment_chars and re.fullmatch(r'\s*[ㅇ○●■□]\s*[^\n:：]{1,60}\s*',text[a:b])
                    and not is_spec(text[a:b])):
                role='heading'
            if text[a:b].strip():fragments.append({'id':f'{node_id}_f{index:02}','node_id':node_id,'start':a,'end':b,'text':text[a:b],
                                                 'expected_role':role,
                                                 'suggested_subject_ids':list(dict.fromkeys(owners.get(node_id,[])))})
    return pack_fragments(fragments,DocumentContext(document),target_chars)

