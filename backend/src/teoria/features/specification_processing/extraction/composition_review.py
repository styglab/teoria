"""Validate missing composition links proposed alongside attribute ownership review."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from teoria.features.specification_processing.extraction.entity_relation_extraction import (
    cyclic_relation_indexes, relation_errors, configuration_boundary_errors,
)


class CompositionLink(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str
    target_id: str
    kind: Literal['component_of', 'physical_part_of']
    attribute_ids: list[str] = Field(min_length=1)
    evidence: list[tuple[str, str]] = Field(min_length=1)


def add_composition_links(graph, document, proposals, attributes=None):
    """Keep original observations; add only grounded, noncyclic links of required targets."""
    if not proposals:
        return {'added': 0, 'rejected': 0}
    entities = {e['id']: e for e in graph['entities']}
    kinds = {key: e.get('kind') for key, e in entities.items()}
    nodes = {n['node_id']: n for n in document['nodes']
             if document.get('document_assessment', {}).get('node_roles', {}).get(n['node_id']) != 'table_of_contents'}
    attributes = {a['id']: a for a in (attributes if attributes is not None else graph.get('attributes', []))}
    relations = graph.setdefault('relations', [])
    keys = {(r['source_id'], r['target_id'], r['kind']) for r in relations}
    existing_ids = {r.get('id') for r in relations}
    added = rejected = 0
    for raw in proposals:
        try:
            link = CompositionLink.model_validate(raw)
        except ValueError:
            rejected += 1
            continue
        key = (link.source_id, link.target_id, link.kind)
        if key in keys:
            continue
        node_ids = [node for node, _ in link.evidence]
        row = (link.source_id, link.target_id, link.kind, 'explicit', node_ids)
        invalid = relation_errors(row, set(entities), kinds, set(nodes))
        invalid.extend(configuration_boundary_errors(link.source_id,link.target_id,link.kind,
            graph.get('composition_inventory')))
        if invalid or any('existing_target' in entities[i].get('document_roles', [])
                          for i in (link.source_id, link.target_id)):
            rejected += 1
            continue
        # A supported option, quantity, or unknown ownership is not proof of supplied composition.
        if any(aid not in attributes or link.source_id not in attributes[aid]['subject_ids']
               or attributes[aid].get('semantic_role') != 'requirement_candidate'
               or attributes[aid].get('semantic_scope') in {'support_limit', 'unknown'}
               for aid in link.attribute_ids):
            rejected += 1
            continue
        if any(not quote.strip() or quote not in nodes[node]['text'] for node, quote in link.evidence):
            rejected += 1
            continue
        rows = [(r['source_id'], r['target_id'], r['kind'], r.get('basis', 'interpreted'),
                 [e['node_id'] for e in r.get('evidence', [])]) for r in relations]
        if len(rows) in cyclic_relation_indexes([*rows, row]):
            rejected += 1
            continue
        number = len(relations) + 1
        while f'rel_composition_{number:03}' in existing_ids:
            number += 1
        identifier = f'rel_composition_{number:03}'
        relations.append({'id': identifier, 'source_id': link.source_id,
                          'target_id': link.target_id, 'kind': link.kind, 'basis': 'explicit',
                          'evidence': [{'node_id': node, 'quote': quote, 'text': nodes[node]['text'],
                                        'native_ref': nodes[node].get('native_ref')} for node, quote in link.evidence],
                          'origin': 'attribute_composition_review',
                          'review_attribute_ids': link.attribute_ids, 'review_status': 'needs_review'})
        keys.add(key)
        existing_ids.add(identifier)
        added += 1
    return {'added': added, 'rejected': rejected}


def assert_composition_preserved(before,after):
    """Attribute stages may append observations, never rewrite the verified composition base."""
    for collection in ('entities','relations'):
        rows=after.get(collection,[]);current={row['id']:row for row in rows}
        if len(current)!=len(rows):raise ValueError('composition contains duplicate '+collection+' IDs')
        for row in before.get(collection,[]):
            if current.get(row['id'])!=row:
                raise ValueError('composition changed during attribute processing: '+collection+' '+row['id'])
    for key in ('inventory_ids','composition_inventory','declared_quantities'):
        if before.get(key)!=after.get(key):
            raise ValueError('composition changed during attribute processing: '+key)
