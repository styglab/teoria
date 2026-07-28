1. 규칙
- Source의 원형을 그대로 표현할 것 
- source_name은 절대 변경하지 않는다.
- 의미를 바꾸지 않는다.
- Source는 Source만 표현한다.
- code도 Source에 둔다.
- path는 record_path만 둔다.
- 원본(OpenAPI, DB, CSV)의 이름을 그대로 사용
- id는 원본 식별자
- 기본 교환 데이터 표준: JSON
- value의 값은 "" 처리
- 소스 파일 네이밍 규칙
```
{provider}_{dataset}_{service}.yaml

- 예시
국세청 사업자등록정보 진위확인 및 상태조회 서비스
nts_business_registration.yaml
```

2. 구조
```
registry
source
specification
  format : API 명세의 표현 형식(OpenAPI, document, WSDL 등)
  version : 기관이 제공하는 API/명세의 버전
  schema_version: OpenAPI/Swagger 규격 버전
access
operations
  request
    query
      fields
    header
      fields
    body
      fields
  response
    control
      fields
    data
      record_path
      fields
  errors
```

