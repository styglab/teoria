# Runtime Contract Registry

Runtime Contract Registry는 Source record와 Capability 입출력을 검증하고
materialize하는 실행 스키마다. 현재 `company`, `public_procurement`,
`assessment` 계약을 제공한다. 지속 가능한 업무 의미와 lifecycle은
PostgreSQL 기반 Business Ontology v2가 소유하며 이 YAML과 구분한다.

## Domain 경계

Domain은 제공기관이나 API별로 나누지 않는다. 같은 식별자로 객체를 합치고, 같은 관계와 사용자 질문 안에서 함께 탐색하는 개념을 하나의 의미 경계로 둔다.

- `company`: 금융위원회와 국세청 등에서 얻은 법인, 사업자등록, 재무와 기업관계를 통합한다.
- `public_procurement`: 조달청 및 향후 다른 Source에서 얻을 입찰공고, 투찰, 낙찰, 계약과 이행정보를 통합한다.
- `assessment`: 회사와 공고 사이에서 수행된 평가, 개별 요건 판단과 그 판단을 뒷받침한 근거를 표현한다.
- 두 Domain은 사업자등록을 통해 계약업체 관계로 연결하되 서로의 객체를 복제하지 않는다.

Source와 Connector는 데이터를 어디서 어떻게 얻는지를 정의하고 Runtime
Contract는 실행 시 데이터 형태를 정의한다. Business Ontology와의 의미 연결은
Semantic Binding이 담당한다.

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

Object Type은 Runtime이 materialize하거나 Capability가 반환하는 데이터 구조다.
지속 가능한 Business Object를 새로 정의할 때는 이 파일이 아니라 Business
Ontology Authoring API를 사용한다.

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

Runtime Contract는 API 호출 순서나 Source별 HTTP 계약을 소유하지 않는다.
Provider wire 계약은 Source Registry가, 변환은 Runtime Mapping이 담당한다.

## 파일 형식

도메인별 파일은 `runtime_contract.yaml`이며 루트 키도 `runtime_contract`를
사용한다. 이전 `ontology.yaml` 파일명과 `ontology` 루트 키 지원은 Registry
`2026.10.06.3`에서 제거됐다.
