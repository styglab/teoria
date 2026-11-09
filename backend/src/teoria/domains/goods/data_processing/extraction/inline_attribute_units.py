"""Recover an omitted unit only beside the observation's anchored source number."""

from copy import deepcopy
import re

from teoria.domains.goods.data_processing.extraction.value_normalization import UNITS, number, normalize_fact
from teoria.domains.goods.data_processing.parsing.document_evidence import literal


def recover_inline_attribute_units(document, attributes):
    """Keep owners/values/operators fixed; ambiguous or nonadjacent source units stay unresolved."""
    nodes = {node['node_id']: node.get('text', '') for node in document['nodes']}
    units = '|'.join(re.escape(unit) for unit in sorted(UNITS, key=len, reverse=True) if UNITS[unit] is not None)
    suffix = re.compile(r'[ \t]*(?:[-‐‑][ \t]*)?(?P<unit>' + units + r')(?![\w/·²³^°-])')
    summary = {'unit_recoveries': 0, 'ambiguous_values': 0}
    for attribute in attributes:
        if (attribute.get('unit_raw') is not None or attribute.get('data_type') != 'number'
                or attribute.get('semantic_role') != 'requirement_candidate'
                or 'model' in attribute.get('property_key', '') or number(attribute.get('value_raw', '')) is None):
            continue
        evidence = attribute.get('evidence', {})
        text = nodes.get(evidence.get('node_id'))
        if text is None:
            continue
        start, end = evidence.get('char_start', 0), evidence.get('char_end', len(text))
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(text):
            continue
        fields = evidence.get('field_spans', {})
        spans = fields.get('value_raw', [])
        if spans:
            if len(spans) != 1 or len(spans[0]) != 2:
                continue
            a, b = spans[0]
            if not isinstance(a, int) or not isinstance(b, int) or not start <= a < b <= end:
                continue
            if literal(text[a:b]) != literal(attribute['value_raw']):
                continue
        else:
            matches = list(re.finditer(r'(?<![\w.,])' + re.escape(attribute['value_raw']) + r'(?![\d.,])', text[start:end]))
            if len(matches) != 1:
                summary['ambiguous_values'] += len(matches) > 1
                continue
            a, b = start + matches[0].start(), start + matches[0].end()
        # Do not cross a source line or search the rest of a wide specification cell.
        match = suffix.match(text, b)
        if match is None:
            continue
        unit = match['unit']
        updated = deepcopy(evidence)
        updated.setdefault('field_spans', {})['value_raw'] = [[a, b]]
        updated['field_spans']['unit_raw'] = [[match.start('unit'), match.end('unit')]]
        if 'char_end' in updated:
            updated['char_end'] = max(end, match.end('unit'))
        if 'quote' in updated:
            updated['quote'] = text[start:updated.get('char_end', len(text))]
        attribute['evidence'] = updated
        attribute['unit_raw'] = unit
        attribute['unit_recovered_from_source'] = True
        attribute['inline_unit_projection'] = {'node_id': evidence['node_id'], 'value_span': [a, b],
                                                'unit_span': [match.start('unit'), match.end('unit')]}
        attribute['normalized'] = normalize_fact(attribute['property_key'], attribute['data_type'],
                                                 attribute['operator'], attribute['value_raw'], unit)
        summary['unit_recoveries'] += 1
    return summary
