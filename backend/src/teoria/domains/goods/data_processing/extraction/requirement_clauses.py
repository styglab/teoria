"""Preserve source descriptions and other clauses without inventing atomic requirements."""
import re


def merge_description_clauses(requirements, document):
    """Join local description passages; never cross another owner's or table cell's boundary."""
    nodes=document['nodes'];positions={n['node_id']:i for i,n in enumerate(nodes)}
    def description(row):
        return row.get('observation_type')=='source_clause' and row.get('category')=='description'
    def node_ids(row):return list(dict.fromkeys(e['node_id'] for e in row.get('evidence',[])))
    output=[]
    for row in requirements:
        previous=output[-1] if output else None
        if previous is None or not description(previous) or not description(row):
            output.append(row);continue
        left=node_ids(previous);right=node_ids(row)
        same_owner=set(previous.get('subject_ids',[]))==set(row.get('subject_ids',[]))
        if not left or not right or not same_owner or not set(left+right)<=positions.keys():
            output.append(row);continue
        if previous.get('text')==row.get('text') and left==right:
            previous['source_observation_ids']=list(dict.fromkeys(
                previous.get('source_observation_ids',[])+row.get('source_observation_ids',[])))
            continue
        a=positions[left[-1]];b=positions[right[0]]
        first=nodes[a];second=nodes[b]
        local=(a<b and all(not n.get('text','').strip() for n in nodes[a+1:b]))
        paragraphs=(first.get('kind')==second.get('kind')=='paragraph'
                    and first.get('parent_id')==second.get('parent_id'))
        # A PDF list item can continue as a paragraph. Require its assessed
        # clause link as well as adjacency; never merge two separate lists.
        list_continuation=(first.get('kind')=='list' and second.get('kind')=='paragraph'
                           and first.get('parent_id')==second.get('parent_id')
                           and any(left[-1] in group and right[0] in group
                                   for group in document.get('document_assessment',{}).get('clause_groups',[])))
        new_item=bool(re.match(r'^\s*(?:\d+[.)]|[가-힣][.)]|[ㅇ○●■□])\s*',row['text']))
        if not local or not (paragraphs or list_continuation) or new_item:
            output.append(row);continue
        previous['text']=previous['text'].rstrip()+' '+row['text'].lstrip()
        previous['evidence']=[*previous['evidence'],*row['evidence']]
        previous['join_basis']='adjacent_description_passages'
        previous['source_observation_ids']=list(dict.fromkeys(
            previous.get('source_observation_ids',[])+row.get('source_observation_ids',[])))
    requirements[:]=output


def preserve_description_attribute(graph, attribute, document, subject_ids):
    """Move only the grounded explanatory passage out of the property list."""
    node_id=attribute['evidence']['node_id']
    node=next(n for n in document['nodes'] if n['node_id']==node_id)
    evidence=attribute['evidence'];start=evidence.get('char_start',0);end=evidence.get('char_end',len(node['text']))
    text=node['text'][start:end]
    clauses=graph.setdefault('requirements',[])
    clause=next((r for r in clauses if r.get('observation_type')=='source_clause'
                 and r.get('text')==text and set(r.get('subject_ids',[]))==set(subject_ids)
                 and [e.get('node_id') for e in r.get('evidence',[])]==[node_id]
                 and (r.get('category')=='description' or document.get('document_assessment',{}).get('node_roles',{}).get(node_id)=='description')),None)
    if clause is None:
        clause={'id':'description_'+attribute['id'],'observation_type':'source_clause','atomic_requirement':False,
                'text':text,'subject_ids':list(subject_ids),'evidence':[{'node_id':node_id,'quote':text,
                'char_start':start,'char_end':end,'native_ref':node.get('native_ref')}],'review_status':'needs_review'}
        clauses.append(clause)
    clause['category']='description'
    clause.setdefault('source_observation_ids',[]).append(attribute['id'])


def validate_description_clause(clause, entity_ids, document):
    """Description text is concatenated source, never a generated summary."""
    from teoria.domains.goods.data_processing.parsing.document_evidence import literal
    if not set(clause.get('subject_ids',[]))<=entity_ids:
        raise ValueError('invalid description subject')
    nodes={n['node_id']:n for n in document['nodes']};pieces=[]
    for evidence in clause.get('evidence',[]):
        node=nodes.get(evidence.get('node_id'))
        if node is None:raise ValueError('invalid description source')
        start=evidence.get('char_start',0);end=evidence.get('char_end',len(node['text']))
        if not isinstance(start,int) or not isinstance(end,int) or not 0<=start<end<=len(node['text']):
            raise ValueError('invalid description bounds')
        quote=node['text'][start:end]
        if evidence.get('quote',quote)!=quote:raise ValueError('description source mismatch')
        pieces.append(quote)
    if not pieces or literal(clause['text'])!=''.join(literal(piece) for piece in pieces):
        raise ValueError('description text must preserve all source passages')


def is_other_requirement(row, document):
    if row.get('category') == 'other' or row.get('observation_type') == 'obligation':
        return True
    roles = document.get('parsed_document', document).get('document_assessment', {}).get('node_roles', {})
    return any(roles.get(e.get('node_id')) in {'general_requirement', 'delivery_requirement'}
               for e in row.get('evidence', []))


def other_requirements(document):
    rows = [r for r in document.get('requirements', []) if is_other_requirement(r, document)]
    source_nodes = {e.get('node_id') for r in rows if r.get('observation_type') == 'source_clause'
                    for e in r.get('evidence', [])}
    # A legacy split duty does not duplicate a preserved original clause at the same node.
    return [r for r in rows if r.get('observation_type') != 'obligation'
            or not any(e.get('node_id') in source_nodes for e in r.get('evidence', []))]


def validate_legacy_obligation(duty, entity_ids, document):
    """Old checkpoints remain readable and source-checked; new runs never generate these."""
    if not set(duty['subject_ids']) <= entity_ids:
        raise ValueError('invalid obligation subject')
    if duty.get('modality') not in {'required','prohibited','recommended','permitted','unknown'} or (duty.get('modality')!='unknown' and not duty.get('modality_raw')):
        raise ValueError('invalid obligation modality')
    nodes = {n['node_id']: n for n in document['nodes']}
    evidence = duty.get('evidence', [])
    if len(evidence) != 1 or evidence[0].get('node_id') not in nodes:
        raise ValueError('invalid obligation evidence')
    evidence = evidence[0]
    text = nodes[evidence['node_id']]['text']
    start, end = evidence.get('char_start'), evidence.get('char_end')
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(text):
        raise ValueError('invalid obligation source span')
    quote = text[start:end]
    if duty.get('text') != quote or evidence.get('quote') != quote:
        raise ValueError('obligation source mismatch')
    from teoria.domains.goods.data_processing.parsing.document_evidence import literal
    raw = [duty.get('action_raw'), duty.get('actor_raw'), duty.get('modality_raw'),
           *duty.get('conditions_raw', [])]
    if not duty.get('action_raw') or any(value is not None and
            (not value.strip() or literal(value) not in literal(quote)) for value in raw):
        raise ValueError('invalid obligation source fields')


def preserve_other_attribute(graph, attribute, document, evidence_node_ids):
    """Retain a general clause without asserting that it applies to every product."""
    nodes = {n['node_id']: n for n in document['nodes']}
    node_id = attribute['evidence']['node_id']
    node = nodes[node_id]
    rows = graph.setdefault('requirements', [])
    clause = next((r for r in rows if r.get('observation_type') == 'source_clause'
                   and r.get('id') == 'clause_' + node_id), None)
    if clause is None:
        clause = {'id': 'clause_' + node_id, 'observation_type': 'source_clause',
                  'atomic_requirement': False, 'text': node['text'],
                  'evidence': [{'node_id': node_id, 'quote': node['text'],
                                'native_ref': node.get('native_ref')}], 'review_status': 'needs_review'}
        rows.append(clause)
    clause.update(category='other', subject_ids=[], application_scope='unspecified')
    clause['classification_evidence_node_ids'] = list(dict.fromkeys(evidence_node_ids))
    clause.setdefault('source_observation_ids', []).append(attribute['id'])
