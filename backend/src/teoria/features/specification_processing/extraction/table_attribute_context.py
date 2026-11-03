"""Recover literal table units and explicitly subdivided purchase quantities."""
from copy import deepcopy
import re

from teoria.features.specification_processing.extraction.document_context import DocumentContext
from teoria.features.specification_processing.extraction.value_normalization import UNITS,number,normalize_fact
from teoria.features.specification_processing.parsing.document_evidence import literal

HEADER_UNITS=set(UNITS)|{'cc','㎖','ml','㎏','㎝'}
QUANTITY_HEADER=re.compile(r'수량|quantity|q[\'’]?ty',re.I)
UNIT_HEADER=re.compile(r'(?:기본|구매)?단위|units?|uom',re.I)


def _scalar_cell(attribute,cell):
    """A bare numeric cell can inherit a column header; prose with embedded numbers cannot."""
    value=attribute.get('value_raw','')
    if attribute.get('data_type')!='number' or number(value) is None:return False
    text=literal(cell.get('text',''));raw=literal(value)
    if text.count(raw)!=1:return False
    remainder=text.replace(raw,'',1)
    return not remainder or bool(re.fullmatch(r'(?:이상|이하|초과|미만|[<>=≤≥±+~–—-])+',remainder))


def _header_band(context,cell,graph):
    table=context.table_key(cell)
    if table is None:return []
    members={n['node_id']:n for key in context.tables.get(table,[])
             if (n:=context.cells[key]).get('row') is not None}
    supplied=[]
    for entity in graph.get('entities',[]):
        if 'supply_target' not in entity.get('document_roles',[]) or 'procurement_scope' in entity.get('document_roles',[]):continue
        for evidence in entity.get('evidence',[]):
            other=context.cells.get(evidence.get('node_id'))
            if other and context.table_key(other)==table and other.get('row') is not None:
                supplied.append(other['row'])
    first_data=min(supplied) if supplied else min((n['row'] for n in members.values()),default=cell['row'])+1
    # Only the first explicit header band; never treat previous purchase rows as headers.
    return [n for n in members.values() if first_data-3<=n['row']<min(first_data,cell['row'])
            and n.get('text','').strip() and len(n['text'])<=100]


def _recover_missing_quantities(context,graph,attributes):
    """Project literal subdivision cells only when a single purchase-row owner is explicit."""
    observed=set()
    for attribute in attributes:
        evidence=attribute.get('evidence',{})
        observed.update(evidence.get('source_node_ids',[]))
        observed.add(evidence.get('node_id'))
        observed.add(evidence.get('value_evidence',{}).get('node_id'))
    recovered=0
    cells={n['node_id']:n for n in context.cells.values()}
    for node_id,cell in cells.items():
        if node_id in observed or cell.get('row') is None or cell.get('column') is None:continue
        if (cell.get('column_span') or 1)!=1 or (cell.get('row_span') or 1)!=1:continue
        raw=cell.get('text','').strip()
        if not raw or number(raw) is None:continue
        column=[n for n in _header_band(context,cell,graph) if context.overlaps(cell,n,'column')]
        parents=[n for n in column if QUANTITY_HEADER.search(n['text'])]
        if not parents:continue
        parent_row=max(n['row'] for n in parents)
        leaves=[n for n in column if n['row']>parent_row and (n.get('column_span') or 1)==1]
        if not leaves:continue
        last=max(n['row'] for n in leaves)
        if len([n for n in leaves if n['row']==last])!=1:continue
        owners=context.purchase_row_targets(node_id,graph)
        if len(owners)!=1:continue
        attributes.append({'id':'attribute_table_quantity_'+node_id,'subject_ids':sorted(owners),
            'property_key':'quantity','property_raw':None,'property_label':parents[-1]['text'],
            'property_label_origin':'source_table_header','data_type':'number','operator':'eq',
            'operator_raw':None,'value_raw':raw,'unit_raw':None,'qualifiers_raw':[],
            'normalized':normalize_fact('quantity','number','eq',raw,None),
            'ontology_property_id':None,'review_status':'needs_review','origin':'literal_table_quantity',
            'semantic_role':'requirement_candidate','semantic_scope':'batch_total',
            'assertion_kind':'specification_requirement','modality':'unspecified',
            'evidence':{'node_id':node_id,'native_ref':cell.get('native_ref'),
                        'char_start':cell.get('text','').find(raw),'char_end':cell.get('text','').find(raw)+len(raw)}})
        recovered+=1
    return recovered


def recover_table_attribute_context(document,graph,attributes):
    """Keep literal cell evidence for every added field, preserving value/owner/operator."""
    context=DocumentContext(document)
    summary={'unit_recoveries':0,'quantity_scope_recoveries':0,'ambiguous_units':0,
             'derived_quantities':_recover_missing_quantities(context,graph,attributes)}
    for attribute in attributes:
        evidence=attribute.get('evidence',{});node_id=evidence.get('node_id')
        if attribute.get('origin')=='validated_inventory_quantity' or not node_id:continue
        cell=context.cells.get(node_id)
        if cell is None or cell.get('row') is None or cell.get('column') is None or (cell.get('column_span') or 1)!=1:continue
        if not _scalar_cell(attribute,cell):continue
        headers=_header_band(context,cell,graph)
        column=[n for n in headers if context.overlaps(cell,n,'column')]
        additions=[];unit=None;qualifier=None
        if attribute.get('unit_raw') is None:
            units={}
            for header in column:
                for match in re.finditer(r'[（(\[]\s*([^）)\]]+?)\s*[）)\]]',header['text']):
                    candidate=match[1].strip()
                    if candidate in HEADER_UNITS:units.setdefault(candidate,[]).append(header['node_id'])
            if len(units)==1:
                unit=next(iter(units));additions.extend(units[unit])
            elif len(units)>1:summary['ambiguous_units']+=1
        quantity_headers=[n for n in column if QUANTITY_HEADER.search(n['text'])]
        if quantity_headers:
            parent_row=max(n['row'] for n in quantity_headers)
            leaves=[n for n in column if n['row']>parent_row and (n.get('column_span') or 1)==1]
            if leaves:
                last=max(n['row'] for n in leaves);leaves=[n for n in leaves if n['row']==last]
                if len(leaves)==1 and not any(literal(q)==literal(leaves[0]['text']) for q in attribute.get('qualifiers_raw',[])):
                    qualifier=leaves[0]['text'];additions.extend([n['node_id'] for n in quantity_headers]+[leaves[0]['node_id']])
            if attribute.get('unit_raw') is None and unit is None:
                unit_columns=[n for n in headers if UNIT_HEADER.fullmatch(literal(n['text']))]
                candidates={}
                table=context.table_key(cell)
                for key in context.tables.get(table,[]):
                    other=context.cells[key]
                    raw=other.get('text','').strip()
                    if raw not in HEADER_UNITS or not context.overlaps(cell,other,'row'):continue
                    for header in unit_columns:
                        if context.overlaps(header,other,'column'):
                            candidates.setdefault(raw,set()).update([key,header['node_id']])
                if len(candidates)==1:
                    unit=next(iter(candidates));additions.extend(sorted(candidates[unit]))
                elif len(candidates)>1:summary['ambiguous_units']+=1
        if unit is None and qualifier is None:continue
        # Multi-cell evidence is already used for validated inventory quantities. Retain
        # the original precise numeric span separately, without pretending a header is inline.
        attribute['evidence']={'source_node_ids':list(dict.fromkeys([node_id,*additions])),
                               'value_evidence':{k:deepcopy(v) for k,v in evidence.items() if k!='quote'},
                               'scope':'explicit same-table column/row context'}
        attribute['table_context_projection']={'unit':unit,'quantity_scope':qualifier,
                                               'source_node_ids':list(dict.fromkeys(additions))}
        if unit is not None:
            attribute['unit_raw']=unit;attribute['unit_recovered_from_source']=True
            attribute['normalized']=normalize_fact(attribute['property_key'],attribute['data_type'],attribute['operator'],attribute['value_raw'],unit)
            summary['unit_recoveries']+=1
        if qualifier is not None:
            attribute['qualifiers_raw']=[*attribute.get('qualifiers_raw',[]),qualifier]
            summary['quantity_scope_recoveries']+=1
    return summary
