# Teoria Provider API

`teoria-provider-api`는 Platform Source와 Pipeline Connector가 공유하는 작은 Python 라이브러리다. 서비스가 아니므로 포트, 데이터베이스, 독립 Docker 배포를 갖지 않는다.

## 책임

포함 범위:

- Provider API wire contract schema
- 입력 검증과 HTTP request 생성
- HTTP 실행, credential interface, retry와 구조화 오류
- 응답 record path와 wire type 검증

포함하지 않는 범위:

- Semantic Registry, Ontology, Mapping, Capability
- Pipeline Definition, Prefect Flow, 정규화와 DB 적재
- MCP 또는 Runtime HTTP client

## 코드와 설정 위치

구현은 `packages/provider_api/src/`, 테스트는 `packages/provider_api/tests/`,
패키지 계약은 `packages/provider_api/pyproject.toml`에 둔다.

## 요청이 처리되는 순서

`schema.py`가 wire 계약을 표현하고 `validator.py`가 계약을 검증한다.
`request_builder.py`는 입력을 HTTP 요청으로 만들고, `executor.py`는 인증정보 주입·HTTP
실행·재시도를 수행한다. `response_validator.py`는 record path와 응답 타입을 검증한다.
인증정보 경계는 `secrets.py`, 오류와 진단은 `errors.py`·`diagnostics.py`에서 찾는다.

Platform과 Pipelines가 각자의 실행·적재 정책을 유지하면서 같은 Provider wire 처리만
공유한다. 소유 프로젝트의 Registry, Flow, Runtime을 라이브러리에서 import하지 않는다.

## 검증

```bash
uv run --locked --package teoria-provider-api pytest packages/provider_api/tests
```

## 상세 문서

호출 프로젝트의 계약 작성은 [Source authoring](../platform/registry/source_authoring.md)과
[Connector 작성](../pipelines/connectors.md)을 따른다.
