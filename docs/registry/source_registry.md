# Source Registry

Source Registry는 외부 제공기관의 API 계약을 원형에 가깝게 표현한다. Ontology 의미나 업무 흐름을 넣지 않는다.

## 위치와 이름

```text
registries/sources/{source_id}.yaml
references/providers/{provider}/{source}/metadata.yaml
registries/sources/verification_cases/{source_id}/{operation_id}.yaml
```

파일명과 `source.id`는 같아야 한다. Source ID는 일반적으로 `{provider}_{service}` 형태의 `snake_case`를 사용한다. 원본 필드와 파라미터 ID는 대소문자를 포함해 제공기관 표기를 보존한다.

## 구조

아래 예시는 상위 구조를 보여주는 축약본이다. 실제 Registry의 `components.objects`와 `operations`에는 각각 하나 이상의 완전한 정의가 필요하다.

```yaml
registry:
  version: 1.0.0
  registered_at: "2026-07-30"

source:
  id: nts_business_registration
  name: 국세청 사업자등록정보 진위확인 및 상태조회 서비스
  provider:
    organization: 국세청
    distribution: 공공데이터포털
  type: api
  specification:
    format: swagger
    version: "2.0"
    api_version: "v1.1"
    source_document: API문서.md
  access:
    base_url: https://example.go.kr/api/v1
    authentication:
      type: api_key
      in: query
      name: serviceKey
      credential_env: TEORIA_SOURCE_EXAMPLE_API_KEY
  components:
    objects: []
  operations: []
```

`specification.format`은 API 명세가 Swagger, OpenAPI, 문서 등 어떤 형식으로 제공됐는지를 나타낸다. 공통 값 타입을 정의하는 Data Type Registry와는 다른 개념이다.

## Components와 Fields

반복되는 응답 또는 요청 객체는 `components.objects`에 한 번 정의하고 `ref`로 참조한다. 단순 필드는 `data_type`, 배열은 `type: array`와 `items`, 중첩 객체는 `type: object`와 `fields`를 사용한다. 요청 필수값은 컨테이너의 `required`에 원본 필드 ID를 나열한다.

원천 코드가 문서에 정의되어 있으면 필드의 `values`에 원본 `value`와 `label`을 기록한다. 이를 Ontology의 표준 Value Set으로 직접 대체하지 않는다.

## Operation

Operation은 다음 내용을 가진다.

- 원본 동작을 나타내는 `id`, `method`, `path`
- 재시도 판단에 사용하는 `idempotent`
- `request.query`, `request.header`, `request.body`
- 성공 응답의 `content_type`, `http_status`, control과 data
- 반복 레코드 위치를 나타내는 `record_path`
- 페이지 기반 API의 `pagination`
- 제공기관이 정의한 오류 상태와 코드

`GET`과 `HEAD`에는 request body를 선언할 수 없다. 응답 `data`는 `ref` 또는 인라인 `fields` 중 정확히 하나를 가져야 한다.

## 인증정보

Registry에는 실제 키가 아니라 환경변수 이름인 `credential_env`만 기록한다. 이름은 `TEORIA_SOURCE_<SOURCE_ID>_API_KEY` 형식을 권장한다. 실제 값은 로컬 `.env` 또는 배포 환경의 secret store에서 주입한다.

## 근거 문서 연결

`specification.source_document`를 선언한 Source에는 대응하는 Provider Reference metadata가 있어야 한다. metadata의 `source`, `registry`, `files`가 Source와 실제 문서를 올바르게 가리키는지 전체 Registry 검증에서 확인한다.

## 검증

정적 구조만 검사:

```bash
teoria verify source --profile static --source nts_business_registration
```

요청 생성까지 검사:

```bash
teoria verify source \
  --profile build \
  --source nts_business_registration \
  --operation get_business_registration_status \
  --input registries/sources/verification_cases/nts_business_registration/get_business_registration_status.yaml
```

실제 호출과 응답 계약까지 검사하려면 API 키를 주입하고 `--profile live`를 사용한다.
