# Source Registry

Source Registry는 Semantic Runtime이 직접 접근하는 API 또는 Database 계약이다. Ingestion Worker 전용 API는 [Connector](../ingestion/connectors.md)로 정의한다.

## 선택과 위치

| 접근 방식 | 정의 위치 |
|---|---|
| Runtime이 외부 API 직접 호출 | `platform/registries/sources/{source_id}.yaml` |
| Runtime이 정규 DB 조회 | 같은 위치의 `type: database` Source |
| Prefect가 외부 API 수집 | `pipelines/connectors/{connector_id}.yaml` |

API Source에는 다음 파일을 함께 둔다.

```text
platform/registries/sources/{source_id}.yaml
platform/references/providers/{provider}/{source}/metadata.yaml
platform/registries/sources/verification_cases/{source_id}/{operation_id}.yaml
```

파일명과 `source.id`는 같아야 한다. Teoria ID는 `snake_case`, 원본 필드와 파라미터 ID는 제공기관 표기를 보존한다.

## API Source

```yaml
registry:
  version: 1.0.0
  registered_at: "2026-07-31"
source:
  id: provider_service
  provider:
    organization: 제공기관
  type: api
  specification:
    format: openapi
    version: "3.0"
    source_document: api.yaml
  access:
    base_url: https://example.go.kr/api
    authentication:
      type: api_key
      in: query
      name: serviceKey
      credential_env: TEORIA_SOURCE_PROVIDER_SERVICE_API_KEY
  components:
    objects:
      - id: record
        fields:
          - id: value
            data_type: string
  operations:
    - id: get_record
      method: GET
      path: /record
      idempotent: true
      response:
        content_type: application/json
        http_status: 200
        data:
          record_path: data
          ref: record
```

- 반복 객체는 `components.objects`에 두고 `ref`로 재사용한다.
- 필드는 `data_type`, `ref`, `type` 중 하나로 정의한다.
- 원천 코드값은 필드 `values`에 보존한다.
- Operation에는 method, path, request, response, 오류와 pagination을 기록한다.
- JSON 실행 계약이면 형식 파라미터에 `default: json`을 둘 수 있다.
- 실제 키는 기록하지 않고 `credential_env`만 둔다.

## Database Source

```yaml
source:
  id: teoria_public_procurement
  type: database
  access:
    engine: postgresql
    connection_env: TEORIA_RUNTIME_DATA_DATABASE_URL
  relations:
    - id: contracts
      relation: public_procurement.contracts
      primary_key: [unified_contract_number]
      fields:
        - id: unified_contract_number
          data_type: string
```

Mapping은 `<source>.<relation>.<field>`로 필드를 참조한다. 접속 문자열은 환경변수로만 주입한다.

## 검증

```bash
# 전체 Registry
uv run --locked --package teoria-platform teoria validate platform/registries

# 요청 생성
uv run --locked --package teoria-platform teoria verify source \
  --profile build \
  --source {source_id} \
  --operation {operation_id} \
  --input platform/registries/sources/verification_cases/{source_id}/{operation_id}.yaml
```

실제 호출은 `--profile live`를 사용한다. 신규 작성 절차는 [Source Authoring Guide](source-authoring.md)를 따른다.
