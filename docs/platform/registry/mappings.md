# Mapping 값 변환과 객체 생성

Mapping은 Source record의 필드를 Runtime Object의 Property로 변환한다.
필드·타입·identity는 Runtime 계약을 따르고, 지속 가능한 업무 의미는 Published
Ontology가 정의한다. YAML의 `ontology: company`는 이 실행 계약의 namespace를
참조하는 기존 필드명이며 Business Ontology 작성이나 Semantic Binding을 대신하지 않는다.

아래는 구조를 설명하기 위해 일부 필드만 보인 예다.

```yaml
mapping:
  id: company
  ontology: company
  bindings:
    legal_entity.legal_name:
      - field: fsc_company_basic.get_company_overview.response.corpNm
```

필드 참조:

- API: `<source>.<operation>.request|response.<path>`
- Database: `<source>.<relation>.<field>`
- Target: `<object_type>.<property>`

한 Property 아래 여러 항목은 독립 binding이다. 여러 필드를 함께 변환할 때만 이름 있는 객체로 묶는다.

```yaml
postal_address.full_address:
  - field:
      base: source.operation.response.baseAddress
      detail: source.operation.response.detailAddress
    decode: company.combine_korean_address
```

- `decode`: Source 표현을 Runtime Property 값으로 변환
- `encode`: Runtime 입력을 Source 요청 값으로 변환
- `role`: 같은 레코드의 동일 Object Type 역할 구분

Codec은 `backend/src/teoria/features/semantic_modeling/registry/codecs/`의 실제 함수이며 Registry에서는 `company.function_name`처럼 짧게 참조한다.

`materializations`는 binding 결과로 객체 identity와 Link endpoint를 만든다. 내부 ID, 고정값, 수집시각과 링크 생성 규칙은 binding에 넣지 않는다.

## 다른 연결과의 구분

이 문서는 Source record를 Runtime object로 변환하는 실행 계약이다.
Ontology Concept와 Glossary·자산·API·Capability를 연결하는
[Semantic Binding](../ontology.md)과 구분한다. API 응답을 정규 DB로 적재하는 변환은
Pipelines 기능별 `normalization.py`가 소유한다.

## 게시 Ontology를 참조하는 API Mapping

선택적인 `bindings.<target>[].meaning`으로 API 필드와 게시된 업무 속성의 의미 연결을 선언한다.
기존 Mapping의 Runtime 대상 ID·codec 이름은 유지한다. 의미를 선언하지 않은 과거 Mapping을
자동으로 Ontology 연결로 승격하지 않는다.

```yaml
meaning:
  ontology:
    version_id: 게시_버전_UUID
    namespace: goods
    version: '1'
    checksum: 게시_artifact_SHA256
  concept_id: 속성_Stable_Concept_UUID
  api_field_binding_id: 승인된_API_Field_Binding_UUID
  information_kind: declared_value
  scope: per_component
  unit:
    source_unit: TB
    canonical_unit: GB
    multiplier: '1000'
  operator: eq
  effective_at_field: effective_at
```

위 내용은 형태 설명이며 운영 Source나 사용할 수 있는 UUID가 아니다. 신규 공급 API의 필드·단위는
제공기관 원문으로 검증한 후 Source Registry와 API Field Binding을 작성한다.
이 경로의 첫 검증은 합성 메모리 응답이며 비활성 조달 API나 업무 Capability를 재활성화하지 않는다.

Runtime bundle 생성과 적재는 다음을 검사한다.

- 게시 버전 ID·namespace·version·checksum, Stable Concept ID의 속성 존재와 소유 유형.
- 명시한 승인 API Field Binding의 대상 Source·Operation·응답 객체·필드·계약 버전·승인 주체·유효 기간.
- Binding의 `represents`/`equivalent` 관계. 미지원 조건부 연결·관련성 연결은 적용하지 않는다.
- Source 필드·Runtime 속성·Ontology 속성의 자료형, scalar cardinality, 기준/허용 단위.
- 같은 Runtime 속성에 서로 다른 개념 버전·정보 성격·범위를 섞지 않았는지.

처음 지원하는 값은 scalar 숫자·텍스트와 단일 응답 필드다. 의미를 선언한 경로에서는 임의 codec·qualifier를 적용하지 않으며, 실행이 생성하는 ID·시각 속성에 업무 관찰을 덧붙이지 않는다.
여러 필드를 합쳐 해석하는 codec이나 요청 필드에 의미 승인을 추정하지 않는다. 단위 환산은 프로파일과 같은 `UnitConversion` 정책을 사용한다.
현재 변환은 기존 바이트 단위·수량 표기 범위이며 다른 물리량의 새 환산을 추측하지 않는다.
개발용 원본 Registry만 적재한 경로에서는 검증된 의미 plan이 없으므로 이 Mapping을 실행하지 않는다.
Production은 계속 checksum을 검증한 bundle만 사용하며 작성 DB를 읽지 않는다.

## 정보 성격과 결과 근거

문서의 요구조건(`requirement`), API의 제조사 명시값(`declared_value`), 측정값(`measurement`)은
입력 형식으로 추정하지 않고 검토된 연결·적용 규칙에서 정한다. 측정값에는 실제 측정 시각과
실행이 응답을 읽은 시각을 구분한다. `effective_at_field`를 지정하면 원천 ISO 날짜/시각을 보존한다.

의미 연결이 있는 결과 객체에는 `semantic_observations`를 제공한다. 각 관찰은 게시 개념·대상 참조·
정보 성격·operator·scope·정규값·원래 값/단위·Source 필드·Binding·Mapping·기준 시각을 보존한다.
같은 물품 속성의 값·시점·조건이 충돌하면 여러 관찰을 보존하고, 평면 속성은
`semantic_conflicts`로 보류한다. 마지막 응답으로 의미 충돌을 덮어쓰지 않는다.

합성 문서/API 검증과 불일치 통제는
`backend/tests/integration/test_document_api_meanings.py`에서 실행한다. 실제 API Live 품질 평가를 뜻하지 않는다.
