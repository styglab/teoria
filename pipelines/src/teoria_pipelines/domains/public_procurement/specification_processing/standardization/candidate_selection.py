"""Choose source meanings conservatively; server adoption requires explicit selection."""


def select_definition(candidate,document,attribute,rule_set):
    if rule_set=='server':
        from .server_rules import select_typed_definition,select_source_constraint
        choice,reason=select_typed_definition(candidate,document,attribute)
        if choice is not None:return choice,'typed_definition',reason
        choice,reason=select_source_constraint(candidate,document,attribute)
        return choice,'source_constraint',reason
    # Preserve every unknown expression as a candidate; a name match does not prove meaning.
    return None,None,'unresolved_meaning_preserved_as_candidate'
