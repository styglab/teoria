"""Value and unit checks shared by published property consumers."""
from decimal import Decimal, InvalidOperation, localcontext

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UnitConversion(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    source_unit: str = Field(min_length=1)
    canonical_unit: str = Field(min_length=1)
    multiplier: Decimal = Field(default=Decimal('1'), gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def supported_conversion(self):
        scales = {'B':Decimal(1), 'kB':Decimal(1000), 'MB':Decimal(1000)**2,
                  'GB':Decimal(1000)**3, 'TB':Decimal(1000)**4, 'KiB':Decimal(1024),
                  'MiB':Decimal(1024)**2, 'GiB':Decimal(1024)**3, 'TiB':Decimal(1024)**4}
        count_aliases = {'EA':'개', 'ea':'개'}
        if count_aliases.get(self.source_unit,self.source_unit) == count_aliases.get(self.canonical_unit,self.canonical_unit):
            expected = Decimal(1)
        elif self.source_unit in scales and self.canonical_unit in scales:
            expected = scales[self.source_unit] / scales[self.canonical_unit]
        else:
            raise ValueError('unsupported unit conversion; preserve as an unresolved candidate')
        if self.multiplier != expected:
            raise ValueError('incorrect unit conversion multiplier')
        return self


def validate_property_unit(prop, conversion):
    if conversion.canonical_unit != prop.get('unit'):
        raise ValueError('canonical unit differs from ontology property')
    if prop.get('allowed_units') and conversion.source_unit not in prop['allowed_units']:
        raise ValueError('source unit is outside the published property unit policy')


def normalize_property_number(raw, value_type, conversion):
    """Convert explicit numeric values without inferring a unit or losing precision."""
    if isinstance(raw, bool) or raw is None:
        raise ValueError('invalid_number')
    try:
        number = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise ValueError('invalid_number') from None
    if not number.is_finite():
        raise ValueError('invalid_number')
    with localcontext() as context:
        multiplier = conversion.multiplier if conversion is not None else Decimal(1)
        context.prec = max(28, len(number.as_tuple().digits) + len(multiplier.as_tuple().digits) + 10)
        value = number * multiplier
    if value_type in {'integer','int'} and value != value.to_integral_value():
        raise ValueError('non_integral_count')
    return {'kind':'number', 'decimal':format(value,'f'), 'unit':conversion.canonical_unit if conversion is not None else None}
