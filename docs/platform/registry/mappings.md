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
