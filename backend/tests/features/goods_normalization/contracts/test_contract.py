from decimal import Decimal
import pytest
from pydantic import ValidationError
from teoria.features.goods_normalization.contracts import UnitRule,RequirementRule


def test_decimal_and_binary_capacity_units_are_not_conflated():
    assert UnitRule(source_unit='TB',canonical_unit='GB',multiplier='1000').multiplier==Decimal('1000')
    assert UnitRule(source_unit='GiB',canonical_unit='GB',multiplier='1.073741824').multiplier==Decimal('1.073741824')
    with pytest.raises(ValidationError):UnitRule(source_unit='TB',canonical_unit='GB',multiplier='1024')
    with pytest.raises(ValidationError):UnitRule(source_unit='G',canonical_unit='GB')
    with pytest.raises(ValidationError):UnitRule(source_unit='kg',canonical_unit='GB')
    assert UnitRule(source_unit='EA',canonical_unit='개').multiplier==1
    with pytest.raises(ValidationError):UnitRule(source_unit='Core',canonical_unit='Thread')


def test_numeric_policy_requires_units_and_known_semantic_scope():
    data={'rule_id':'test','target_concept_id':'00000000-0000-0000-0000-000000000001',
          'property_concept_id':'00000000-0000-0000-0000-000000000002','source_property_keys':['capacity'],
          'roles':['requirement_candidate'],'scopes':['unknown'],'value_type':'number'}
    with pytest.raises(ValidationError):RequirementRule.model_validate(data)
    data['scopes']=['per_module']
    with pytest.raises(ValidationError,match='explicit unit'):RequirementRule.model_validate(data)
