# Ontology Registry

Ontology Registry는 AI와 애플리케이션이 공유할 도메인 의미를 Object Type, Property, Link Type으로 표현한다. 현재 한국 기업정보 도메인은 `registries/domains/company/ontology.yaml`에 있다.

## Object Type

Object Type은 독립적으로 식별하고 조회할 도메인 개체다.

```yaml
- id: legal_entity
  name: 법인
  description: 대한민국 법률에 따라 설립된 법적 실체
  primary_key: corporate_registration_number
  properties:
    - id: corporate_registration_number
      name: 법인등록번호
      description: 등기기관이 법인에 부여하는 13자리 식별번호
      data_type: corporate_registration_number
```

- `description`은 AI가 개념의 포함·제외 범위와 다른 객체와의 차이를 판단할 수 있게 작성한다.
- `primary_key`는 같은 Object Type의 Property 중 하나를 참조한다.
- Property는 `data_type` 또는 `value_set` 중 정확히 하나를 가진다.
- 복수 값은 `collection: list`로 명시한다.
- `examples`는 의미 경계를 이해하는 데 실질적으로 도움이 될 때만 둔다.

원천 식별자가 없는 관측·확인 객체는 시스템 생성 식별자를 primary key로 사용할 수 있다. 이 경우 설명에 어떤 값으로 생성하는지와 원천기관 식별자가 아님을 명시한다.

## Link Type

Link Type은 Object Type 사이에서 허용되는 의미적 관계를 정의한다.

```yaml
- id: legal_entity_has_business_registration
  description: 법인이 세무상 사업자등록을 보유한다
  source: legal_entity
  target: business_registration
```

방향은 `source`와 `target`으로 충분히 명확하게 표현하고, 실제 데이터 연결은 Mapping의 materialization이 생성한다. 현재 모델은 cardinality를 강제하지 않는다.

## 시간에 따라 변하는 정보

모든 변경 가능 속성을 별도 관측 객체로 만들 필요는 없다. 현재 상태를 조회하는 데 충분한 값은 본체 Property와 `observed_at` 계열 Property로 표현할 수 있다. 이력 자체가 독립적인 사실이고 여러 시점의 비교가 필요한 납세자 상태, 재무제표, 확인 결과 등은 별도 Object Type으로 모델링한다.

Ontology는 API 필드명, 호출 순서, transform 함수나 Source별 코드를 포함하지 않는다.
