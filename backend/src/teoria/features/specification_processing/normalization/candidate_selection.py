"""Choose source meanings conservatively; server adoption requires explicit selection."""


def select_definition(candidate,document,attribute,rule_set,*,auto_apply_source_literals=False):
    if rule_set=='server':
        from teoria.features.specification_processing.normalization.server_rules import select_typed_definition,select_source_constraint
        choice,reason=select_typed_definition(candidate,document,attribute)
        if choice is not None:return choice,'typed_definition',reason
        choice,reason=select_source_constraint(candidate,document,attribute)
        return choice,'source_constraint',reason
    if auto_apply_source_literals:
        import hashlib
        import json
        from teoria.features.specification_processing.parsing.document_evidence import attribute_is_grounded
        from teoria.features.specification_processing.normalization.standard_application import signature
        context = signature(document, attribute, rule_set)
        if (not attribute['subject_ids'] or 'unresolved' in context[0]
                or len(context[0]) != 1 or context[4] == 'unknown' or context[5] == 'unknown'):
            return None, None, 'unresolved_source_context'
        if not attribute_is_grounded(document, attribute):
            return None, None, 'source_condition_mismatch'
        # This ID denotes a literal extraction contract, never an Ontology concept.
        digest = hashlib.sha256(json.dumps(context, ensure_ascii=False).encode()).hexdigest()[:24]
        definition = {'id': 'source_literal_' + digest,
            'label': attribute.get('property_raw') or attribute['property_key'],
            'definition': '원문 값·단위·연산자·조건을 그대로 보존하는 추출용 규칙.',
            'semantic_maturity': 'source_literal', 'published': False,
            'numeric_ordering_allowed': False, 'approval_policy': 'grounded_source_literal_v1'}
        return {'definition': definition}, 'source_literal', 'grounded_source_literal_policy'
    # A name match does not prove business meaning.
    return None,None,'unresolved_meaning_preserved_as_candidate'
