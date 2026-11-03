"""Separate primary composition from deeper source observations without rewriting either."""

MAX_PRIMARY_LEVELS = 3


def composition_hierarchy(document):
    """Classify accepted composition paths; never invent a parent or promote a withheld child."""
    entities = {e['id']: e for e in document.get('entities', [])}
    relations = document.get('relations', [])
    kinds = {'component_of', 'physical_part_of'}
    related = {key for key, e in entities.items() if e.get('kind') in {'activity', 'document'}
               or set(e.get('document_roles', [])) & {'existing_target', 'work_scope_target'}}
    supplied = {key for key, e in entities.items() if 'supply_target' in e.get('document_roles', [])}
    while True:
        additions = {r['source_id'] for r in relations if r.get('kind') in kinds
                     and r.get('target_id') in related and r['source_id'] not in supplied}
        if additions <= related:
            break
        related.update(additions)
    parents = {}
    for r in relations:
        child, parent = r.get('source_id'), r.get('target_id')
        if child not in entities or parent not in entities or child == parent or {child, parent} & related:
            continue
        physical = all(entities[key].get('kind') in {None, 'product', 'equipment', 'group'} for key in (child, parent))
        software = all(entities[key].get('kind') == 'software' for key in (child, parent))
        if (r.get('kind') not in kinds or not (physical or software and r['kind'] == 'component_of')
                or r.get('review_status') == 'held' or not r.get('evidence')
                or not (r.get('basis') == 'explicit' or r['kind'] == 'component_of' and r.get('basis') == 'interpreted')):
            continue
        parents.setdefault(child, set()).add(parent)
    children = {}
    for child, targets in parents.items():
        if len(targets) == 1:
            children.setdefault(next(iter(targets)), []).append(child)
    proposed = {r.get('source_id') for r in [*relations, *document.get('held_relations', [])]
                if r.get('kind') in kinds and r.get('target_id') not in related}
    inventory = document.get('composition_inventory', {})
    root = inventory.get('root_id')
    purchased = set(supplied)
    if inventory.get('basis') == 'configuration_list' and inventory.get('integrated_scope'):
        purchased.add(root)
    if inventory.get('basis') == 'supply_list':
        purchased.update(inventory.get('item_ids', []))
    candidates = purchased if purchased or 'composition_inventory' in document else set(children)
    roots = [key for key in entities if key in candidates and key not in related and key not in proposed]
    levels = {}
    pending = [(key, 1) for key in roots]
    while pending:
        key, level = pending.pop()
        if key in levels:
            continue
        levels[key] = level
        pending.extend((child, level + 1) for child in children.get(key, []))
    return {'schema_version': 1, 'max_primary_levels': MAX_PRIMARY_LEVELS, 'root_ids': roots,
            'primary_entity_ids': [key for key in entities if 0 < levels.get(key, 0) <= MAX_PRIMARY_LEVELS],
            'detail_entity_ids': [key for key in entities if levels.get(key, 0) > MAX_PRIMARY_LEVELS],
            'levels': levels}
