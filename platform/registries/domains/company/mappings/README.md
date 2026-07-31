# Mapping Registry

Mapping은 Source 필드가 어떤 Ontology Property를 의미하는지 정의한다. Property 의미·타입은 Ontology에서만 관리한다.

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

- `decode`: Source 표현을 Ontology 값으로 변환
- `encode`: Ontology 입력을 Source 요청 값으로 변환
- `role`: 같은 레코드의 동일 Object Type 역할 구분

Codec은 `platform/src/teoria/runtime/mapping/functions/`의 실제 함수이며 Registry에서는 `company.function_name`처럼 짧게 참조한다.

`materializations`는 binding 결과로 객체 identity와 Link endpoint를 만든다. 내부 ID, 고정값, 수집시각과 링크 생성 규칙은 binding에 넣지 않는다.
