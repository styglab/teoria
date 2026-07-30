# Capability Registry

Capability Registry는 의미 기반 입력, 실행할 Source operation 및 반환할 Ontology 객체와 링크를 선언한다.
API 계약은 Source Registry, 응답 의미는 Mapping Registry에 있으므로 Capability에서 반복하지 않는다.

도메인별 Capability는 `registries/domains/{domain}/capabilities/`에 두며, MCP 도구 이름은 Capability `id`와 같다.

```yaml
capability:
  id: get_company_profile
  description: 법인등록번호로 기업 기본정보를 조회한다
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
- Capability 입력과 Source 요청 필드의 연결은 Mapping Registry의 request binding으로 해석한다.
- `returns`: `<ontology>.<object_type>` 또는 `<ontology>.<link_type>`

단계는 작성된 순서대로 실행한다. 각 의미 입력에는 호출할 모든 operation의 request binding이 있어야 하고, 반환 객체에는 호출 operation의 response binding이 있어야 한다. 조건, 반복 및 오류 정책은 실제 요구가 생길 때 선택 필드로 확장한다.

복합 요청은 `fields`와 `collection: list`로 같은 레코드에 속하는 입력을 묶는다. 도메인 값은 `property`로 Mapping의 request binding을 사용하고, Ontology 사실로 취급하지 않을 Capability 전용 값은 `data_type + field`로 직접 요청 필드에 연결한다.

실행은 `CapabilityRunner`가 입력 binding, `encode`, Source 요청 생성과 호출, 응답 검증, `decode`를 순서대로 수행한다.

```python
from teoria.runtime.capability import CapabilityRunner

result = await CapabilityRunner().run(
    catalog,
    "get_business_registration_status",
    {"business_registration_numbers": ["0000000000"]},
)
```

결과의 `objects`에는 identity로 병합되고 내부 ID가 부여된 Ontology 객체가, `links`에는 source/target 객체 ID를 가진 실제 Ontology 링크가 들어간다. 원본 응답은 기본적으로 제외되며 진단이 필요할 때만 `include_raw_responses=True`로 요청한다.

Runtime은 Source별 timeout과 retry, Capability 전체 deadline과 최대 페이지 수를 적용한다. 실패는 capability, source, operation, page와 retry 가능 여부가 포함된 구조화 오류로 전달한다.
