"""Normalize literal values and units without assigning ontology concepts."""
import re
from decimal import Decimal, InvalidOperation

UNITS={'GB':'GB','MB':'MB','TB':'TB','G':None,'GHz':'GHz','MHz':'MHz','kHz':'kHz','Hz':'Hz',
       'mm':'mm','㎜':'mm','cm':'cm','m':'m','kg':'kg','g':'g','V':'V','kV':'kV','W':'W','kW':'kW','MPa':'MPa',
       'mL/min':'mL/min','mL':'mL','uL':'µL','μL':'µL','µL':'µL','nm':'nm','m/z':'m/z','Core':'core','core':'core',
       'Thread':'thread','thread':'thread',
       'msec':'ms','ms':'ms','sec':'s','s':'s','min':'min','h':'h','일':'일','년':'년','개월':'개월','주일':'주일',
       'set':'set','SET':'set','System':'System','EA':'개','ea':'개','개':'개','대':'대','식':'식','부':'부','%':'%',
       '℃':'°C','°C':'°C','lux':'lux','L':'L','mmHg':'mmHg'}

def number(value):
    value=value.strip()
    if not re.fullmatch(r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?',value):return None
    try:return str(Decimal(value.replace(',','')))
    except InvalidOperation:return None


def normalize_fact(property_key,data_type,operator,value_raw,unit_raw):
    result={'operator':operator,'value':None,'unit':UNITS.get(unit_raw),'unit_status':'not_stated' if unit_raw is None else 'normalized' if UNITS.get(unit_raw) is not None else 'unmapped',
            'comparison_rule':None,'status':'raw_preserved','notes':[]}
    if data_type=='identifier' or 'model' in property_key:
        result['value']=value_raw;result['notes'].append('Identifier ordering requires a separate product comparison rule.');return result
    if '상온' in value_raw or re.search(r'ambient|room\s*temp',value_raw,re.I):
        result['value']=value_raw;result['notes'].append('Temperature depends on ambient reference; absolute bounds are unresolved.');return result
    if data_type=='range':
        match=re.fullmatch(r'\s*([+-]?[\d,.]+)\s*(?:~|～|–|—|-|\bto\b)\s*([+-]?[\d,.]+)\s*',value_raw)
        if match:
            low,high=number(match[1]),number(match[2])
            if low is not None and high is not None and Decimal(low)<=Decimal(high):result['value']={'min':low,'max':high}
    elif data_type=='number':
        raw=value_raw.strip()
        if operator=='tolerance' and raw.startswith('±'):
            magnitude=number(raw[1:]);result['value']={'tolerance':magnitude} if magnitude is not None else None
        else:result['value']=number(raw)
    if result['value'] is None:result['value']=value_raw
    numeric=(data_type=='number' and (isinstance(result['value'],dict) or number(str(result['value'])) is not None)) or (data_type=='range' and isinstance(result['value'],dict))
    if numeric and operator!='raw' and (unit_raw is None or result['unit'] is not None):
        result['comparison_rule']='numeric_requirement';result['status']='normalized_candidate'
    elif unit_raw and result['unit'] is None:result['notes'].append('Unit is unresolved; no comparison or conversion applied.')
    return result

