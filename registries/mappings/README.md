# Mapping Registry

Mapping Registry는 Source Registry의 필드를 Ontology Registry의 속성에 대응시킨다.
객체·속성의 의미와 타입은 Ontology Registry에만 정의하며 Mapping에서 반복하지 않는다.
내부 식별자, 고정값, 수집시각, 객체 생성과 링크 생성은 Mapping Registry에 두지 않는다.

```yaml
mapping:
  id: company
  ontology: company
  bindings:
    legal_entity.legal_name:
      - field: fsc_company_basic.get_company_overview.response.corpNm
```

한 Ontology 속성 아래의 목록 항목은 서로 독립적인 binding이다. 값을 합치거나 우선순위를 정한다는 의미가 아니다.

```yaml
legal_entity.corporate_registration_number:
  - field: first_source.operation.response.crno
  - field: second_source.operation.response.crno
```

여러 Source 필드를 하나의 codec에 함께 전달할 때만 하나의 `field` 객체에 이름을 붙여 선언한다.

```yaml
postal_address.full_address:
  - field:
      base_address: source.operation.response.base_address
      detail_address: source.operation.response.detail_address
    decode: company.combine_korean_address
```

응답 필드는 `decode`로 Source 표현을 Ontology 값으로 변환하고, 요청 필드는 `encode`로 Ontology 값을 Source 표현으로 변환한다.
Codec은 `src/teoria/transforms/` 아래의 실제 Python 함수이며 `<module>.<function>`으로 참조한다.
Codec이 없으면 Source 필드와 Ontology 속성을 같은 표현으로 대응시킨다.

```yaml
financial_statement.fiscal_year:
  - field: source.operation.response.bizYear
    decode: common.to_integer
  - field: source.operation.request.query.bizYear
    encode: common.format_year
```

동일 응답 레코드에 같은 Object Type이 여러 역할로 나타나면 `role`로 구분한다.

```yaml
legal_entity.corporate_registration_number:
  - field: source.operation.response.crno
    role: reference_entity
  - field: source.operation.response.relatedCrno
    role: related_entity
```

`materializations`는 binding된 속성으로 객체 identity를 계산하고 실제 링크를 만드는 규칙이다. `bindings`는 필드 의미 대응만 담당하고, 객체 병합·내부 ID·관측시각·링크 endpoint는 materialization이 담당한다.

```yaml
materializations:
  source.operation:
    objects:
      reference_entity:
        type: legal_entity
        identity: [corporate_registration_number]
      related_entity:
        type: legal_entity
        identity: [corporate_registration_number]
    links:
      - type: organization_relationship_has_related_entity
        source: relationship
        target: related_entity
```
