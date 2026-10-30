"""Source sections and table neighborhoods for extraction; never infer BOM ownership."""

import re
import unicodedata


def section_rank(node):
    """Recognize presentation boundaries, not domain entity types."""
    text=unicodedata.normalize('NFKC',node.get('text','')).strip()
    if node.get('kind') in {'heading','title','section_title'}:
        level=node.get('heading_level')
        return level if isinstance(level,int) and level>0 else 1
    if node.get('kind')!='paragraph' or len(text.splitlines()[0] if text else '')>160:
        return None
    if re.match(r'^[IVXLCDM]+[.)]\s+',text):
        return 0
    dotted=re.match(r'^(\d+(?:\.\d+)+)\.?\s+',text)
    if dotted:
        return 1+dotted[1].count('.')
    if re.match(r'^\d+\.\s+',text):
        return 1
    if re.match(r'^[가-힣]\.\s+',text):
        return 2
    return None


class DocumentContext:
    """Select original nodes with stable IDs and no generated source text."""

    def __init__(self,document):
        self.nodes=document['nodes']
        self.lookup={n['node_id']:n for n in self.nodes}
        self.paths={};self.cells={};self.tables={};self.sections={}
        stack=[]
        for node in self.nodes:
            node_id=node['node_id']
            rank=(None if document.get('document_assessment',{}).get('node_roles',{}).get(node_id)=='table_of_contents'
                  else section_rank(node))
            # Numbered content inside a table cell is not a document heading.
            cell=next((n for n in self.ancestors(node_id) if n.get('kind')=='cell' or n.get('row') is not None),None)
            if rank is not None and cell is None:
                while stack and stack[-1][0]>=rank:
                    stack.pop()
                stack.append((rank,node_id))
            path=tuple(key for _,key in stack)
            self.paths[node_id]=path
            self.sections.setdefault(path,[]).append(node_id)
            if cell is not None:
                self.cells[node_id]=cell
                table=self.table_key(cell)
                if table is not None:
                    self.tables.setdefault(table,[]).append(node_id)

    def ancestors(self,node_id):
        seen=set()
        while node_id in self.lookup and node_id not in seen:
            seen.add(node_id)
            node=self.lookup[node_id]
            yield node
            node_id=node.get('parent_id')

    def table_key(self,cell):
        parent=cell.get('parent_id')
        if parent in self.lookup:
            return ('parent',parent)
        source=cell.get('source_table_id')
        return ('source',source) if source is not None else None

    def group_key(self,node_id):
        cell=self.cells.get(node_id)
        table=self.table_key(cell) if cell is not None else None
        if table is not None:
            return ('table',table)
        path=self.paths.get(node_id,())
        if path:
            return ('section',path)
        node=self.lookup.get(node_id,{})
        return ('parent',node.get('parent_id'))

    def extraction_structure(self,node_ids):
        """Transmit section paths and effective cell coordinates, including nested cell text."""
        cells=[]
        for node in self.nodes:
            key=node['node_id']
            cell=self.cells.get(key)
            if key not in node_ids or cell is None:
                continue
            table=self.table_key(cell)
            if table is not None:
                cells.append([key,table[1],cell.get('row'),cell.get('column'),
                              cell.get('row_span') or 1,cell.get('column_span') or 1])
        return {'section_paths':{key:list(path) for key,path in self.paths.items() if key in node_ids and path},
                'table_cells':cells}

    @staticmethod
    def overlaps(a,b,axis):
        start_a=a.get(axis);start_b=b.get(axis)
        if start_a is None or start_b is None:
            return False
        span=axis+'_span'
        return start_a<start_b+(b.get(span) or 1) and start_b<start_a+(a.get(span) or 1)

    def related_ids(self,node_id):
        """Keep ancestors, section contents and table labels, using only source nodes."""
        if node_id not in self.lookup:
            return set()
        selected={n['node_id'] for n in self.ancestors(node_id)}
        path=self.paths[node_id]
        selected.update(path)
        cell=self.cells.get(node_id)
        table=self.table_key(cell) if cell is not None else None
        if table is not None:
            members=self.tables[table]
            first_row=min((self.cells[key].get('row') for key in members if self.cells[key].get('row') is not None),default=None)
            for key in members:
                other=self.cells[key]
                if (self.overlaps(cell,other,'row') or
                    (first_row is not None and other.get('row')==first_row and self.overlaps(cell,other,'column'))):
                    selected.add(key)
                    selected.update(n['node_id'] for n in self.ancestors(key))
        else:
            parent=self.lookup[node_id].get('parent_id')
            members=[key for key in self.sections[path] if self.lookup[key].get('parent_id')==parent]
            selected.update(members)
        # Unnumbered clauses before a subsection can apply to all its children.
        for depth in range(1,len(path)):
            selected.update(self.sections.get(path[:depth],[]))
        return selected

    def select(self,attributes,graph):
        anchors={key for a in attributes for key in
                 ([a.get('evidence',{}).get('node_id')]+a.get('evidence',{}).get('source_node_ids',[])) if key in self.lookup}
        selected=set()
        for key in anchors:
            selected.update(self.related_ids(key))
        # Flat evidence has no reliable boundary: preserve the previous full context.
        def has_boundary(key):
            cell=self.cells.get(key)
            return bool(self.paths[key] or self.lookup[key].get('parent_id') or
                        (cell is not None and self.table_key(cell) is not None))
        if not anchors or any(not has_boundary(key) for key in anchors):
            return [n for n in self.nodes if n.get('kind')!='image' and n.get('text','').strip()]
        owners={key for a in attributes for key in a.get('subject_ids',[])}
        for clause in graph.get('requirements',[]):
            if clause.get('observation_type')=='source_clause' and any(e.get('node_id') in anchors for e in clause.get('evidence',[])):
                owners.update(clause.get('subject_ids',[]))
        for entity in graph['entities']:
            if any(e.get('node_id') in selected for e in entity.get('evidence',[])):
                owners.add(entity['id'])
        parents={}
        for relation in graph['relations']:
            if relation['kind'] in {'component_of','physical_part_of','specification_for','in_procurement_scope'} and relation.get('basis')!='ambiguous':
                parents.setdefault(relation['source_id'],[]).append(relation['target_id'])
        pending=list(owners)
        while pending:
            for parent in parents.get(pending.pop(),[]):
                if parent not in owners:
                    owners.add(parent);pending.append(parent)
        # IE scopes may explicitly link common conditions outside the local section.
        # Keep those clauses for the target and its ancestors; never traverse siblings.
        for clause in graph.get('requirements',[]):
            subjects=set(clause.get('subject_ids',[]))
            if clause.get('observation_type')=='source_clause' and subjects and subjects<=owners:
                for evidence in clause.get('evidence',[]):
                    key=evidence.get('node_id')
                    if key in self.lookup:
                        selected.update(n['node_id'] for n in self.ancestors(key))
                        selected.update(self.paths[key])
        for entity in graph['entities']:
            if entity['id'] in owners:
                for evidence in entity.get('evidence',[]):
                    key=evidence.get('node_id')
                    if key in self.lookup:
                        selected.update(n['node_id'] for n in self.ancestors(key))
        return [n for n in self.nodes if n['node_id'] in selected and n.get('kind')!='image']


def pack_fragments(fragments,context,target_chars=2200):
    """Keep logical scope IDs while batching small sections into bounded calls."""
    chunks=[];current=[];size=0
    for fragment in fragments:
        key=context.group_key(fragment['node_id'])
        if current and size+len(fragment['text'])>target_chars:
            chunks.append(current);current=[];size=0
        current.append({**fragment,'context_group':key});size+=len(fragment['text'])
    if current:
        chunks.append(current)
    return chunks
