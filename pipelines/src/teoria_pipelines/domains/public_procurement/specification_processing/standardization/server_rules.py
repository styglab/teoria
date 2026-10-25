"""Reviewed server meanings and conservative value handling; no publication or tracing."""
from datetime import date
from decimal import Decimal,InvalidOperation
import re
from ..parsing.document_evidence import literal, source_quote

META={
 'inventory_declared_quantity':('명시 공급·구성 목록 수량','explicit_target','count'),
 'component_quantity_requirement':('구성 대상 수량 요구','hardware_component','count'),
 'cpu_model':('CPU 모델 요구','processor','identifier'),
 'cpu_family':('CPU 제품군 요구','processor','identifier_options'),
 'cpu_pcie_capability':('CPU PCIe 지원 규격','processor','text'),
 'cpu_supported_memory_type':('CPU 지원 메모리 규격','processor','text'),
 'cpu_cores_per_processor':('CPU당 코어 수','processor','integer'),
 'cpu_total_cores':('시스템 전체 CPU 코어 수','processor_set','integer'),
 'cpu_thread_count':('CPU 스레드 수','processor','integer'),
 'cpu_max_clock':('CPU 최대·부스트 클럭','processor','quantity'),
 'cpu_l3_cache_capacity':('CPU L3 캐시 용량','processor','quantity'),
 'cpu_cache_capacity_unspecified_level':('CPU 캐시 용량 — 레벨 미명시','processor','quantity'),
 'cpu_supported_memory_transfer_rate':('CPU 메모리 컨트롤러 지원 전송률','processor','quantity'),
 'memory_module_capacity':('메모리 모듈당 용량','memory_module','quantity'),
 'memory_total_capacity':('시스템 총 메모리 용량','memory_set','quantity'),
 'memory_generation':('DDR 메모리 세대','memory','identifier'),
 'memory_module_form':('메모리 모듈 형태','memory_module','identifier'),
 'memory_composite_specification':('메모리 복합 규격 원문','memory','text'),
 'memory_ecc':('메모리 오류정정 규격 요구','memory','text'),
 'memory_transfer_rate':('메모리 전송률','memory','quantity'),
 'memory_clock_frequency':('메모리 클럭 주파수 — 원문 단위 기준','memory','quantity'),
 'memory_supported_capacity':('확장·지원 가능한 메모리 용량','memory_slot','quantity'),
 'gpu_model':('GPU 모델','gpu','identifier'),
 'gpu_supported_model_options':('지원 가능한 GPU 모델 선택지','gpu','identifier_options'),
 'gpu_memory_capacity':('GPU 메모리 용량','gpu','quantity'),
 'gpu_memory_type':('GPU 메모리 규격','gpu','identifier'),
 'gpu_cuda_cores':('GPU CUDA 코어 수','gpu','integer'),
 'gpu_tensor_cores':('GPU Tensor 코어 수','gpu','integer'),
 'drive_capacity':('개별 드라이브 용량 요구','drive','quantity'),
 'storage_capacity':('스토리지 시스템 용량 — raw/usable 미명시','storage_system','quantity'),
 'storage_raw_capacity':('스토리지 전체 raw 용량','storage_system','quantity'),
 'tape_capacity_specification':('테이프 복합 용량 원문','tape_media','text'),
 'drive_protocol':('드라이브 접속 프로토콜','drive','identifier'),
 'drive_connection_specification':('드라이브 복합 접속 규격','drive','text'),
 'drive_bay_connection_specification':('베이 지원 접속 규격','drive_bay','text'),
 'storage_object_api':('객체 스토리지 API','storage_system','identifier'),
 'drive_link_speed':('드라이브 데이터 링크 속도','drive','quantity'),
 'drive_rotation_speed':('드라이브 회전 속도','drive','quantity'),
 'drive_media_type':('드라이브 매체 종류','drive','identifier'),
 'drive_flash_type':('플래시 메모리 기술','drive','identifier'),
 'drive_usage_class':('드라이브 용도·등급','drive','text'),
 'network_speed':('네트워크 포트 속도 요구','network','quantity'),
 'controller_cache_capacity':('스토리지 컨트롤러 캐시 용량','storage_controller','quantity'),
 'power_capacity':('PSU 출력 용량','power_supply','quantity'),
 'power_redundancy':('전원 중복 구성 요구','power_supply','text'),
 'chassis_height':('섀시 랙 장착 높이','chassis','quantity'),
 'chassis_form_factor':('섀시 형태','chassis','identifier'),
 'delivery_duration_requirement':('납품·설치 소요 기간 요구','procurement_condition','duration'),
 'delivery_calendar_deadline':('납품 기한 날짜','procurement_condition','date'),
 'delivery_deadline_text':('납품 기한 조건 원문','procurement_condition','text'),
 'warranty_duration':('보증 기간','procurement_condition','duration'),
}


def entity_type(e):
 n=e['name'].lower();kind=e.get('kind')
 if e.get('basis_role')=='document_scope':return 'document_scope'
 if kind=='activity':return 'service'
 if kind=='software':return 'software'
 if kind=='document':return 'document'
 if re.search(r'테이프|lto.?[0-9]',n):return 'tape_media'
 if re.search(r'스위치|switch|\bhub\b',n):return 'network_switch'
 if re.search(r'\bnas\b|스토리지|storage',n) and not re.search(r'컨트롤러|controller',n):return 'storage_system'
 if re.search(r'워크스테이션|workstation',n):return 'workstation'
 if re.search(r'서버|\bserver\b|클러스터|\bnode\b|노드',n):return 'server'
 if re.search(r'gpu|gpgpu|그래픽|vram',n):return 'gpu'
 if re.search(r'\bcpu\b|processor|프로세서|중앙처리|xeon|epyc',n):return 'processor'
 if re.search(r'ram.*slot|메모리.*슬롯',n):return 'memory_slot'
 if re.search(r'dimm|\bram\b|memory|메모리|\bddr[3456]\b',n):return 'memory_module' if 'dimm' in n else 'memory_set'
 if re.search(r'disk bay|drive bay|drive.*bay|m\.2.*port|디스크.*베이',n):return 'drive_bay'
 if re.search(r'raid|스토리지.*컨트롤러|storage.*controller|sas.*controller',n):return 'storage_controller'
 if re.search(r'ssd|hdd|nvme|디스크|\bdisk\b',n):return 'drive'
 if re.search(r'psu|power supply|전원공급|파워서플라이',n):return 'power_supply'
 if re.search(r'네트워크|network|\bnic\b|이더넷|ethernet|포트|\blan\b',n):return 'network'
 if re.search(r'섀시|샤시|chassis|랙|\brack\b',n):return 'chassis'
 return 'unresolved'








def decimal_literal(text):
 if not re.fullmatch(r'[+]?\d[\d,]*(?:\.\d+)?',text.strip()):return None
 try:return format(Decimal(text.strip().replace(',','')).normalize(),'f')
 except InvalidOperation:return None


def normalized_value(property_id,a):
 raw=a['value_raw'];unit=a['unit_raw'];expected=META[property_id][2]
 if property_id=='chassis_form_factor':return {'kind':'identifier','text':'rackmount','raw_text':raw,'resolution':'resolved'}
 if property_id=='chassis_height' and unit is None:
  m=re.search(r'(\d+(?:\.\d+)?)\s*U\b',raw,re.I)
  if m:raw=m[1];unit='U'
 if expected in {'text','identifier','identifier_options'}:
  return {'kind':expected,'text':re.sub(r'\s+',' ',raw).strip(),'raw_text':a['value_raw'],'resolution':'resolved','numeric_ordering_allowed':False}
 if expected=='date':
  m=re.search(r'(20\d{2})[.년/-]\s*(\d{1,2})[.월/-]\s*(\d{1,2})',raw)
  if m:
   try:return {'kind':'date','value':date(*map(int,m.groups())).isoformat(),'resolution':'resolved'}
   except ValueError:pass
  return {'kind':'unresolved','raw_text':raw,'unit_raw':unit,'resolution':'invalid_or_ambiguous_date'}
 if property_id=='drive_rotation_speed' and unit and unit.lower()=='rpm' and re.fullmatch(r'\d+(?:\.\d+)?K',raw,re.I):
  return {'kind':'quantity','decimal':format(Decimal(raw[:-1])*1000,'f'),'unit':'rpm','resolution':'resolved','rule':'explicit_kilo_rpm_literal'}
 number=decimal_literal(raw)
 unit_maps={'Core':'core','core':'core','코어':'core','Ghz':'GHz','GHz':'GHz','MHz':'MHz','MT/s':'MT/s','U':'U','W':'W','GB':'GB','TB':'TB','MB':'MB','Gbps':'Gb/s','Gb/s':'Gb/s','rpm':'rpm',
            '년':'year','년간':'year','years':'year','개월':'month','일':'day','주':'week'}
 if expected=='count':
  if number is None or Decimal(number)!=Decimal(number).to_integral_value():return {'kind':'unresolved','raw_text':raw,'unit_raw':unit,'resolution':'non_integer_count'}
  return {'kind':'count','decimal':number,'unit_text':unit,'resolution':'resolved'}
 if expected=='integer':
  if number is None or Decimal(number)!=Decimal(number).to_integral_value():return {'kind':'unresolved','raw_text':raw,'unit_raw':unit,'resolution':'non_integer_count'}
  return {'kind':'count','decimal':number,'unit':'thread' if property_id=='cpu_thread_count' else 'core','resolution':'resolved','unit_rule':'property_intrinsic_count'}
 if number is not None and unit in unit_maps:
  return {'kind':'duration' if expected=='duration' else 'quantity','decimal':number,'unit':unit_maps[unit],'resolution':'resolved','unit_policy':'as_stated_no_cross_unit_conversion','calendar_basis':'calendar_unit_no_date_calculation' if expected=='duration' else None}
 if expected=='duration' and unit in unit_maps:
  m=re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*[~～–-]\s*(\d+(?:\.\d+)?)\s*',raw)
  if m:return {'kind':'duration_range','min_decimal':m[1],'max_decimal':m[2],'unit':unit_maps[unit],'resolution':'resolved'}
 return {'kind':'unresolved_quantity','raw_text':raw,'unit_raw':unit,'resolution':'ambiguous_unit_or_value','reason':'G/Gb/M/K 또는 시간 분모가 없는 단위를 추정·치환하지 않음'}


# Server-only candidate hypotheses and adoption contracts.

FAMILIES = [
 ('manufacturer','제조사','identity','manufacturer'),
 ('country_of_origin','원산지','identity','country_of_origin'),
 ('model','제품 모델 식별자','identity','model model_name product_model'),
 ('installation_location','설치 장소','installation','installation_location'),
 ('delivery_location','납품 장소','delivery','delivery_location'),
 ('network_interface','네트워크 접속 규격','network_interface','network_interface'),
 ('network_port_count','네트워크 포트 수','port_count','network_port_count lan_port_count'),
 ('port_count','포트 수 — 종류별 검토','port_count','port_count'),
 ('memory_slot_count','메모리 슬롯 수','slot_count','memory_slot_count dimm_slot_count'),
 ('drive_bay_count','드라이브 베이 수','bay_count','drive_bay_count bay_count nvme_bay_count'),
 ('expansion_slot_count','확장 슬롯 수','slot_count','slot_count'),
 ('slot_interface','슬롯 접속 규격','slot_capability','slot_interface'),
 ('component_quantity','구성 대상 수량','quantity','drive_quantity drive_count gpu_count gpu_capacity processor_count processor_quantity memory_module_count module_count module_quantity'),
 ('supported_gpu_count','지원 가능한 GPU 수','supported_quantity','supported_gpu_count'),
 ('cpu_thermal_design_power','CPU 열설계전력','tdp','thermal_design_power'),
 ('power_output','PSU 정격 출력','rated_output','power_rating'),
 ('power_redundancy','전원 중복 구성','redundancy','power_redundancy'),
 ('power_efficiency','전원 효율 등급','efficiency','efficiency_level efficiency_rating'),
 ('memory_clock','메모리 클럭 주파수','clock','memory_frequency'),
 ('memory_rating','메모리 등급 표기','rating','memory_rating'),
 ('form_factor','형태·크기 복합 표현','form_factor','form_factor'),
 ('drive_form_factor','드라이브 형태·크기','form_factor','drive_form_factor drive_size bay_size storage_form_factor'),
 ('supported_drive_size','지원 드라이브 형태·크기','supported_form_factor','supported_drive_size'),
 ('hot_swap','핫스왑 요구·지원','hot_swap','hot_swap hot_swap_support'),
 ('operating_system','운영체제 요구','software_requirement','operating_system operating_system_options'),
 ('raid_configuration','RAID 구성 요구','configuration','raid_configuration'),
 ('raid_support','지원 RAID 기능','supported_configuration','raid_support'),
 ('service_duration','서비스 제공 기간','service_period','service_duration'),
 ('training_duration','교육 시간','training_duration','training_duration'),
 ('training_count','교육 횟수','training_count','training_count'),
 ('training_audience','교육 대상','training_audience','training_audience'),
 ('training_content','교육 내용','training_content','training_content training_subject'),
 ('inspection_frequency','점검 주기·횟수','inspection_frequency','inspection_frequency'),
 ('support_response_time','지원 응답 시간','response_time','response_time'),
 ('onsite_response_deadline','현장 대응 기한','onsite_response','onsite_response_deadline onsite_service_start_deadline'),
 ('product_authenticity','제품 정품 요구','authenticity','component_authenticity product_authenticity'),
 ('product_condition','제품 신품·상태 요구','condition','component_condition product_condition'),
 ('document_submission','문서 제출 요구','document_submission','document_submission submission_requirement required_delivery_document required_delivery_documents'),
 ('submission_timing','문서 제출 시점','submission_timing','submission_timing'),
 ('document_content','제출 문서 내용','document_content','required_content'),
 ('installation_included','설치·설정 포함 요구','installation_included','installation_and_configuration_included'),
 ('intended_use','사용 목적','purpose','intended_use workload supported_workloads'),
 ('firmware_version','펌웨어 버전 요구','firmware','firmware_version'),
]

FAMILY_BY_KEY = {key:(concept,label,scope) for concept,label,scope,keys in FAMILIES for key in keys.split()}

def existing_proposal(concept, target, scope, attribute):
    """Require explicit property meaning plus target and unit; proposals are never applied."""
    if concept=='model' and target in {'processor','gpu'}:
        return target.replace('processor','cpu')+'_model'
    if concept=='memory_clock' and target in {'memory_module','memory_set'} and attribute['unit_raw']=='MHz':
        return 'memory_clock_frequency'
    if concept=='power_output' and target=='power_supply' and attribute['unit_raw']=='W':
        return 'power_capacity'
    if concept=='power_redundancy' and target=='power_supply':return 'power_redundancy'
    if concept=='component_quantity':
        key=attribute['property_key']
        allowed = {'drive'} if key in {'drive_quantity','drive_count'} else {'gpu'} if key in {'gpu_count','gpu_capacity'} else {'processor'} if key in {'processor_count','processor_quantity'} else {'memory_module','memory_set'}
        if target in allowed:return 'component_quantity_requirement'
    if concept=='form_factor' and target in {'server','chassis'} and re.fullmatch(r'\s*\d+(?:\.\d+)?\s*U\s*',attribute['value_raw'],re.I):
        return 'chassis_height'
    return None

CONTRACTS = [
 ('cpu_thermal_design_power',{'processor'},'cpu_thermal_design_power','CPU 열설계전력','quantity',{'W'}),
 ('manufacturer',{'server','processor','memory_module','memory_set'},'hardware_manufacturer','하드웨어 제조사','text',set()),
 ('country_of_origin',{'server','processor'},'hardware_country_of_origin','하드웨어 원산지 원문','text',set()),
 ('model',{'server'},'server_model','서버 모델 식별자','identifier',set()),
 ('model',{'memory_module'},'memory_module_model','메모리 모듈 모델 식별자','identifier',set()),
 ('model',{'network_switch'},'network_switch_model','네트워크 스위치 모델 식별자','identifier',set()),
 ('installation_location',{'server'},'server_installation_location','서버 설치 장소·지정 조건','text',set()),
 ('delivery_location',{'server'},'server_delivery_location','서버 납품 장소','text',set()),
 ('network_interface',{'network'},'network_interface_specification','네트워크 접속 복합 규격','text',set()),
 ('network_port_count',{'network'},'network_port_count','네트워크 포트 수','count',{'Port','port',None}),
 ('memory_slot_count',{'memory_slot'},'memory_slot_count','메모리 슬롯 수','count',{'DIMM slot','DIMMs',None}),
 ('drive_bay_count',{'drive_bay'},'drive_bay_count','드라이브 베이 수','count',{'Bay','베이',None}),
 ('service_duration',{'service'},'service_duration','서비스 제공 기간 — 보증 기간과 별개','duration',{'년','year','개월'}),
 ('training_count',{'service'},'training_count','명시 교육 횟수','count',{'회'}),
 ('training_duration',{'service'},'training_session_duration','명시 교육 회차·기간별 시간','duration',{'H','시간'}),
]

TEXT_CONCEPTS = {
 'product_authenticity','product_condition','training_content','training_audience',
 'document_submission','submission_timing','document_content','installation_included',
 'operating_system','raid_configuration','raid_support','network_interface',
 'slot_interface','memory_rating','form_factor','drive_form_factor','supported_drive_size',
 'hot_swap','power_efficiency','firmware_version','intended_use',
 'installation_location','delivery_location','onsite_response_deadline','support_response_time',
}

COUNT_CONCEPTS = {'port_count','network_port_count','memory_slot_count','drive_bay_count','expansion_slot_count','supported_gpu_count'}

def select_typed_definition(candidate,doc,a):
    """Return a property/value only when semantic contract and literal source agree."""
    if candidate['decision']=='hold_for_review':return None,'기존 보류 사유 미해소'
    quote=source_quote(doc,a)
    if not a['value_raw'] or literal(a['value_raw']) not in literal(quote):return None,'원문 값 직접 대조 실패'
    if candidate['role'] not in {'requirement_candidate','existing_reference','supported_capability'}:
        return None,'권장·선택 역할은 별도 검토'
    if candidate['decision']=='existing_definition_proposal':
        pid=candidate['existing_definition_id']
        if existing_proposal(candidate['concept_key'],candidate['target_type_candidate'],candidate['scope'],a)!=pid:
            return None,'기존 정의 연결의 대상·단위 계약 재검사 실패'
        value=normalized_value(pid,a)
        if value['resolution']!='resolved':return None,'기존 정의의 값·단위 처리 조건 미충족'
        return {'property_id':pid,'value':value,'definition':None},'기존 정의·대상·단위·원문 값 대조 통과'
    contract=next((c for c in CONTRACTS if c[0]==candidate['concept_key'] and candidate['target_type_candidate'] in c[1]),None)
    if contract is None:return None,'채택 계약 미정의 또는 적용 대상·범위 추가 검토 필요'
    concept,types,pid,label,kind,units=contract
    if kind in {'quantity','duration','count'}:
        number=decimal_literal(a['value_raw'])
        if number is None or a['unit_raw'] not in units:return None,'명시 수치·허용 단위 조건 미충족'
        if kind=='count' and not re.fullmatch(r'\d+',number):return None,'정수 수량 아님'
        if kind=='count':
            value={'kind':'count','decimal':number,'unit_text':a['unit_raw'],'resolution':'resolved'}
        else:
            unit={'년':'year','개월':'month','H':'hour','시간':'hour'}.get(a['unit_raw'],a['unit_raw'])
            value={'kind':kind,'decimal':number,'unit':unit,'resolution':'resolved','unit_policy':'literal_alias_only_no_date_calculation'}
    else:
        if a['unit_raw'] is not None:return None,'텍스트·식별자에 예상하지 않은 단위 존재'
        value={'kind':kind,'text':re.sub(r'\s+',' ',a['value_raw']).strip(),'raw_text':a['value_raw'],'resolution':'resolved','numeric_ordering_allowed':False}
    definition={'id':pid,'label':label,'target_types':sorted(types),'scope':candidate['scope'],'value_kind':kind,
        'allowed_units_raw':sorted(units,key=lambda v:v or ''),'meaning_source':'bounded_server_corpus_contract',
        'constraints':['직접 원문 값 대조 통과 필요','원문 대상 ID·역할·연산·조건 유지','수량·기간 합산 및 부모·자식 전파 금지','모델 성능 서열·위치 해석·인증 진위 판단 금지'],
        'related_reference':None}
    return {'property_id':pid,'value':value,'definition':definition},'명시 채택 계약·대상·범위·단위·원문 값 대조 통과'

def select_source_constraint(candidate,doc,a):
    if candidate['decision']!='new_definition_proposal':return None,'의미 가설이 없거나 기존 보류 사유 미해소'
    concept=candidate['concept_key'];target=candidate['target_type_candidate']
    if concept not in TEXT_CONCEPTS|COUNT_CONCEPTS:return None,'자동 채택 계약 밖의 의미·대상'
    if target in {'unresolved','multiple_target_types','missing_target'}:return None,'대상 유형 또는 귀속 미확정'
    quote=literal(source_quote(doc,a))
    if not a['value_raw'] or literal(a['value_raw']) not in quote:return None,'원문 값 대조 실패'
    if any(literal(q) not in quote for q in a.get('qualifiers_raw',[])):return None,'원문 조건 대조 실패'
    raw=a['value_raw'].strip()
    if raw.endswith((',',':')) or any(raw.count(left)!=raw.count(right) for left,right in [('(',')'),('[',']')]):
        return None,'불완전한 표현·잘린 목록 가능성'
    # Do not turn ambiguous capacities or an aggregated count into scalar facts.
    if concept in COUNT_CONCEPTS:
        number=decimal_literal(raw)
        if number is None or '.' in number:return None,'단일 정수 개수로 확인되지 않음'
    property_id=f'{concept}_{target}_constraint'
    definition={'id':property_id,'label':candidate['label'],'target_types':[target],
        'scope':candidate['scope'],'value_kind':'source_constraint','meaning_source':'automatic_scoped_source_constraint',
        'constraints':['원문 값·조건 대조 통과','원문 단위·연산자·조건·역할 보존','정품 진위·적합성·납품 여부를 판정하지 않음','수치 비교·단위 환산·관계 재작성 금지'],
        'related_reference':None}
    value={'kind':'source_constraint','text':raw,'unit_raw':a.get('unit_raw'),
        'resolution':'source_preserved','numeric_ordering_allowed':False}
    return {'definition':definition,'value':value},'문맥별 의미 계약과 원문 값·조건 대조 통과; 조건 원문 형태로 채택'


def validate_classification(classification_code):
    if classification_code != "4321150102":
        raise ValueError("server rule set requires computer-server classification 4321150102")
