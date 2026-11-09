"""Separate product extraction blockers from supplementary relationship review."""
from collections import Counter


SUPPLEMENTARY_RELATIONS = frozenset({
    'sends_data_to', 'compatible_with', 'depends_on', 'supports', 'service_for', 'document_for',
})


def held_relation_counts(graph):
    kinds = Counter(r.get('kind', 'unknown') for r in graph.get('held_relations', []))
    supplementary = sum(count for kind, count in kinds.items() if kind in SUPPLEMENTARY_RELATIONS)
    return {'core_held_relations': sum(kinds.values()) - supplementary,
            'supplementary_held_relations': supplementary,
            'held_relations_by_kind': dict(kinds)}


def document_extraction_status(summary, graph, document):
    # Unknown and identity relationships stay blocking: their effect on supplied composition is unknown.
    if (graph.get('inventory_assessment',{}).get('status') in {'reading_failed','reading_uncertain','unresolved'}
            or summary['status'] == 'partial' or document.get('unreadable_ocr_pages')
            or held_relation_counts(graph)['core_held_relations']
            or document.get('document_assessment', {}).get('status') == 'needs_review'):
        return 'partial'
    return 'extracted'
