# Capability 실행 계약

Capability는 검증할 입력, 실행 단계와 반환할 Runtime Object·Link 타입을 선언한다.
업무 의미는 Published Ontology의 Concept 요구사항과 Semantic Binding으로 연결한다.
MCP에 공개할 때 Tool 이름은 Capability ID와 같다.

아래는 구조를 설명하기 위해 일부 필드만 보인 예다.

```yaml
capability:
  id: get_company_profile
  inputs:
    corporate_registration_number:
      property: company.legal_entity.corporate_registration_number
      required: true
  steps:
    - call: fsc_company_basic.get_company_overview
  returns:
    - company.legal_entity
```

- `property`: `<runtime_contract>.<object_type>.<property>`
- `call`: `<source>.<operation>`
- `returns`: `<runtime_contract>.<object_type|link_type>`
- 실행 순서는 `steps` 순서와 같다.

입력→요청은 Mapping의 request binding과 `encode`, 응답→객체는 response binding과 `decode`를 사용한다. Capability 전용 입력은 `data_type + field`로 직접 연결할 수 있다.

Runtime은 timeout, retry, deadline과 최대 페이지를 적용하고 결과를 identity로 병합한 Object·Link와 provenance로 반환한다. 원본 응답은 명시적으로 요청한 진단 상황에서만 포함한다.

## 실행 종류와 외부 노출

`kind`는 `query`, `compute`, `action`으로 실행 성격을 구분한다.
`effects.reads`·`effects.produces`는 조회 대상·비영속 계산 결과,
`effects.creates`·`effects.updates`는 action의 업무 상태 변경을 선언한다.
기존 조회 Capability의 기본 종류는 `query`다.

`exposure: public`인 Capability만 Runtime discovery와 MCP Tool에 노출한다.
조합 실행용 지원 계약은 `internal`로 유지한다. 입력 바인딩은 Ontology와 Runtime의
타입·collection 호환성을 검증한다. Domain 구현과 등록은 [Platform 개발](../development.md),
발행과 실행은 [Runtime](../runtime.md)을 따른다.
