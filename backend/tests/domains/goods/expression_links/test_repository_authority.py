"""Published-concept links must not inherit v1 local-definition mutation authority."""
from teoria.domains.goods.expression_links.expression_link_repository import ExpressionLinkRepository
from teoria.domains.goods.expression_links.legacy.meaning_repository import LegacyMeaningRepository


def test_expression_link_repository_has_no_local_definition_write_interface():
    for name in ('add_concept', 'delete_meaning_records', 'add_mapping'):
        assert not hasattr(ExpressionLinkRepository, name)
        assert callable(getattr(LegacyMeaningRepository, name))
    assert callable(ExpressionLinkRepository.add_ontology_mapping)
    assert callable(ExpressionLinkRepository.concepts)  # Read-only historical import support.
