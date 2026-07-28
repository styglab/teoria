1. 프로젝트명
- 프로젝트 테오리아
- teoria (theoria) - 높은 곳에서 전체를 관찰하여 본질을 이해
- AI context
- source > ontology > mapping > capability

2. 구조
```
Source Registry
↓
Ontology Registry
세상을 정의 (명사)
 - Object
 - Property
 - Relationship
↓
Mapping Registry
↓
Capability Registry
업무를 수행 (동사)
- operation
- decision
- action
- workflow

```

3. 정책
```
- 모든 Registry은 snake_case
- 코드 값 처리에 대해
Source Registry  = 원본 코드와 원본 라벨
Ontology Registry = 표준 의미 값
Mapping Registry  = 원본 코드와 표준 값의 대응

```

4. Source Registry
- 작성 규칙
```
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
```

- 소스 파일 네이밍 규칙
```
{provider}_{dataset}_{service}.yaml

- 예시
국세청 사업자등록정보 진위확인 및 상태조회 서비스
nts_business_registration.yaml
```

- 구조
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

5. 프로젝트 구조
```
registries/             사람이 작성하는 Registry YAML
  source/
  ontology/
  mapping/
  capability/
  format/
src/teoria/
  models/               Registry Pydantic 모델
  registry/             로딩, 참조 해결, 검증 및 진단
tests/
  unit/
  fixtures/
  registry_cases/
```

Source의 필드 ID와 요청 파라미터는 원본 시스템의 표기를 보존한다.
snake_case 규칙은 Registry ID와 Teoria가 정의하는 ID에 적용한다.

6. 개발 및 검증
```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/teoria validate registries
.venv/bin/teoria validate registries --source nts_business_registration
```

Source 요청 생성 검증:

```bash
.venv/bin/teoria verify source \
  --profile build \
  --source nts_business_registration \
  --operation get_business_registration_status \
  --input registries/source/verification_cases/nts_business_registration/get_business_registration_status.yaml
```

`--profile live`는 같은 순서로 실제 API를 호출하고 응답 계약까지 검증한다. 인증정보는 출력이나 Registry에 저장하지 않고 CLI가 안내하는 환경변수로만 주입한다.

현재 검증기는 다음 항목을 확인한다.

- YAML 및 Pydantic 모델 구조
- Source와 Format ID 중복
- Source 내부 Object `ref`
- 공통 Format 참조
- Object 및 Operation ID 중복
- 요청의 `required` 필드 선언 여부
- 필드 타입별 `items`, `fields`, `default`, `max_items` 규칙
- HTTP method, path, content type, 오류 상태 코드
- 응답 `record_path` 문법과 Object 순환 참조

전체 검증 구조와 규칙은 [Source Registry 검증 구조](docs/registry/validation.md)를 참고한다.

