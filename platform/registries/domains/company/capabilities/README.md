# Capability Registry

Capability는 사용자의 의미 입력, 실행할 Source Operation과 반환할 Ontology 타입을 선언한다. MCP Tool 이름은 Capability ID와 같다.

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

- `property`: `<ontology>.<object_type>.<property>`
- `call`: `<source>.<operation>`
- `returns`: `<ontology>.<object_type|link_type>`
- 실행 순서는 `steps` 순서와 같다.

입력→요청은 Mapping의 request binding과 `encode`, 응답→객체는 response binding과 `decode`를 사용한다. Capability 전용 입력은 `data_type + field`로 직접 연결할 수 있다.

Runtime은 timeout, retry, deadline과 최대 페이지를 적용하고 결과를 identity로 병합한 Object·Link와 provenance로 반환한다. 원본 응답은 명시적으로 요청한 진단 상황에서만 포함한다.
