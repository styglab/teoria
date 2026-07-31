# Source Registry Authoring Guide

외부 API 문서로부터 Runtime용 Source Registry를 만드는 절차다. Prefect 전용 API는 [Connector](../ingestion/connectors.md)로 작성한다.

## 산출물

```text
platform/registries/sources/{source_id}.yaml
platform/references/providers/{provider}/{source}/metadata.yaml
platform/references/providers/{provider}/{source}/{document}
platform/registries/sources/verification_cases/{source_id}/{operation_id}.yaml
```

Reference만 등록한 단계는 `metadata.yaml`에 `status: draft`, Source까지 완성되면 `active`를 사용한다.

## 작성 절차

1. 원본에서 제공기관, 버전, base URL, 인증, Operation, 요청·응답 필드, pagination과 오류를 확인한다.
2. `{provider}_{service}` 형식의 안정적인 `snake_case` ID를 정한다.
3. 원본 문서와 `metadata.yaml`을 Reference 경로에 둔다.
4. [Source 템플릿](templates/source.yaml)으로 Source를 작성한다.
5. 실제 secret 대신 `credential_env`를 정의한다.
6. 반복 객체는 Component로 만들고 Operation에서 `ref`한다.
7. 모든 Operation에 공개 가능한 verification case를 만든다.
8. 정적·Build·Live 순서로 검증하고 계약 오류를 수정한 뒤 전체를 재실행한다.

추측으로 필드, 타입, 필수 여부나 코드값을 만들지 않는다. 문서와 실제 응답이 다르면 둘을 구분하고 Live 검증 근거를 남긴다.

## Reference metadata

```yaml
status: draft
provider: 제공기관
source: provider_service
title: API 참고자료
retrieved_at: "2026-07-31"
official_url: null
files:
  - path: api-document.docx
    format: docx
registry: registries/sources/provider_service.yaml
```

`registry`는 `platform/` 기준 상대 경로다. Reference에는 API 키, 개인정보와 비공개 응답을 저장하지 않는다.

## 핵심 규칙

- Source ID와 파일명은 같아야 한다.
- Teoria가 정하는 Source·Object·Operation ID는 `snake_case`다.
- 원본 필드와 파라미터 ID는 대소문자까지 보존한다.
- `specification.source_document`는 Reference 파일명과 일치해야 한다.
- 필드는 `data_type`, `ref`, `type` 중 하나만 사용한다.
- 요청 필수값은 query/header/body 컨테이너의 `required`에 둔다.
- `GET`, `HEAD`에는 body를 선언하지 않는다.
- 응답 `data`는 `ref` 또는 인라인 `fields` 중 하나만 사용한다.
- 조회를 안전하게 반복할 수 있을 때만 `idempotent: true`를 둔다.
- 공통 Data Type이 없으면 재사용 가능성을 확인한 뒤 Core Registry에 추가한다.

페이지 응답 예:

```yaml
pagination:
  type: page_number
  page: {request: query.pageNo}
  page_size: {request: query.numOfRows}
  total_count: response.body.totalCount
response:
  data:
    record_path: response.body.items[]
    ref: record
```

Verification case는 Operation별 요청 section만 포함한다.

```yaml
query:
  pageNo: 1
  numOfRows: 10
```

## 검증

```bash
uv run --locked --package teoria-platform teoria validate platform/registries

uv run --locked --package teoria-platform teoria verify source \
  --profile build \
  --source {source_id} \
  --operation {operation_id} \
  --input platform/registries/sources/verification_cases/{source_id}/{operation_id}.yaml
```

credential을 주입한 실제 검증은 `--profile live`를 사용한다. 원본 전체 응답 대신 필요한 필드 단위의 안전한 fixture만 남긴다.

## 완료 조건

- 모든 ID, path, method, field, type과 pagination이 문서와 일치한다.
- Reference와 Source가 서로 연결된다.
- 모든 Operation에 verification case가 있다.
- Static·Build가 통과하고 가능한 Operation은 Live도 통과한다.
- API 키, 개인정보와 비공개 원본 응답이 커밋되지 않는다.
