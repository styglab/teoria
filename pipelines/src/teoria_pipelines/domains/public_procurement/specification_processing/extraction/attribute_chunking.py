"""Build attribute input fragments while preserving source character offsets."""

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
    for node_id,node in nodes.items():
        text=node['text']
        if not text.strip() or node.get('kind')=='image':continue
        offset=0;start=0;size=0;parts=[]
        for line in text.splitlines(keepends=True):
            if size and size+len(line)>fragment_chars:
                parts.append((start,offset));start=offset;size=0
            offset+=len(line);size+=len(line)
        if offset>start:parts.append((start,offset))
        for index,(a,b) in enumerate(parts):
            if text[a:b].strip():fragments.append({'id':f'{node_id}_f{index:02}','node_id':node_id,'start':a,'end':b,'text':text[a:b],
                                                 'suggested_subject_ids':list(dict.fromkeys(owners.get(node_id,[])))})
    chunks=[];current=[];size=0
    for fragment in fragments:
        if current and size+len(fragment['text'])>target_chars:chunks.append(current);current=[];size=0
        current.append(fragment);size+=len(fragment['text'])
    if current:chunks.append(current)
    return chunks

